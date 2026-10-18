import os
import subprocess
from pathlib import Path
from functools import partial
from os.path import exists, join
from tqdm.contrib.concurrent import process_map

import click
import hashlib
import pandas as pd


def _compute_checksum(file_path: Path | str, method: str = "md5") -> str:
    with open(file_path, "rb") as f:
        md5 = hashlib.file_digest(f, method, _bufsize=1024*1024).hexdigest()
    return str(md5)

def _list_files_in_directory(dir: Path | str) -> list[Path | None]:
    return [f for f in Path(dir).iterdir() if f.is_file()]

def _load_manifest(file_path: Path | str) -> dict:
    try:
        meta = pd.read_csv(file_path)
    except Exception as e:
        raise ValueError(f"Failed to read manifest file: {e} from {file_path}")

    missing_columns = {"file_name", "checksum"} - set(meta.columns)
    assert not missing_columns, f"Missing required columns in manifest: {missing_columns}"

    meta["checksum"] = meta["checksum"].astype(str)
    return meta

def _encrypt_crypt4gh(
    input_file: str | Path,
    recipient_pk: str | Path,
    output_dir: str | Path
) -> None:
    
    input_file = Path(input_file)
    output_dir = Path(output_dir)
    recipient_pk = Path(recipient_pk)

    if not recipient_pk.exists():
        raise FileNotFoundError(f"Recipient public key file does not exist: {recipient_pk}")

    if not input_file.exists(): 
        raise FileNotFoundError(f"Input file does not exist: {input_file}")

    output_file = Path(join(output_dir, input_file.name + ".c4gh"))

    if exists(output_file):
        raise FileExistsError(f"Output file already exists: {output_file}") 

    with input_file.open("rb") as stdin, output_file.open("wb") as stdout:
        process = subprocess.Popen(
            [
                "crypt4gh",
                "encrypt",
                "--recipient_pk",
                str(recipient_pk),
            ],
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        if process.stderr is None:
            raise RuntimeError("Failed to capture crypt4gh stderr")

        for line in process.stderr:
            print(f"[crypt4gh] {line}", end="")

        return_code = process.wait()

    if return_code != 0:
        output_file.unlink(missing_ok=True)
        raise RuntimeError(
            f"crypt4gh encryption failed with exit code {return_code}"
        )

def _decrypt_crypt4gh(
    input_file: str | Path,
    recipient_sk: str | Path,
    output_dir: str | Path
) -> None:
    input_file = Path(input_file)
    output_dir = Path(output_dir)
    recipient_sk = Path(recipient_sk)

    if not recipient_sk.exists():
        raise FileNotFoundError(f"Recipient private key file does not exist: {recipient_sk}")

    if not input_file.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_file}")

    output_file = Path(join(output_dir, input_file.name.rstrip(".c4gh")))

    if exists(output_file):
        raise FileExistsError(f"Output file already exists: {output_file}")

    with input_file.open("rb") as stdin, output_file.open("wb") as stdout:
        process = subprocess.Popen(
            [
                "crypt4gh",
                "decrypt",
                "--sk",
                str(recipient_sk),
            ],
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        if process.stderr is None:
            raise RuntimeError("Failed to capture crypt4gh stderr")

        for line in process.stderr:
            print(f"[crypt4gh] {line}", end="")

        return_code = process.wait()

    if return_code != 0:
        output_file.unlink(missing_ok=True)
        raise RuntimeError(
            f"crypt4gh decryption failed with exit code {return_code}"
        )

@click.group()
def main():
    pass

@main.command()
@click.option("--working-directory", "-w", type=click.Path(exists=True, file_okay=False), required=True)
@click.option("--n-cpus", "-t", type=int, default=4)
def create_manifest(working_directory: Path | str, n_cpus: int):
    to_process = _list_files_in_directory(working_directory)

    if not to_process:
        raise click.ClickException("No files to process. Please check your working directory.") 

    click.echo(f"Computing checksums for {len(to_process)} files using {n_cpus} CPU(s)...")
    checksums = process_map(_compute_checksum, to_process, chunksize=1, max_workers=n_cpus)

    metadata = pd.DataFrame()
    metadata["file_name"] = [path.name for path in to_process]
    metadata["checksum"] = checksums

    metadata.to_csv(
        join(working_directory, "manifest.csv"),
        index=False,
    )

    click.echo(f"Manifest created and saved to {Path(join(working_directory, 'manifest.csv'))}")

@main.command()
@click.option("--working-directory", "-w", type=click.Path(exists=True, file_okay=False), required=True)
@click.option("--manifest-file", "-m", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--n-cpus", "-t", type=int, default=4)
def check(working_directory: Path | str, manifest_file: Path | str, n_cpus: int):
    manifest = _load_manifest(manifest_file)
    expected_files = set(manifest["file_name"].values)
    to_process = [f for f in _list_files_in_directory(working_directory) if f.name in expected_files]

    if not to_process:
        raise click.ClickException("No files to process. Please check your working directory and metadata file.") 

    click.echo(f"Computing checksums for {len(to_process)} files using {n_cpus} process(es)...")
    checksums = process_map(_compute_checksum, to_process, chunksize=1, max_workers=n_cpus)
    
    manifest = (manifest
            .set_index("file_name")
            .loc[[path.name for path in to_process]]
            .assign(checksum_recomputed=checksums)
            .reset_index()
        )

    manifest["checksum_match"] = manifest["checksum"] == manifest["checksum_recomputed"]
    manifest.to_csv(
        join(working_directory, "manifest_validation_report.csv"),
        index=False,
    )

@main.command()
@click.option("--working-directory", "-w", type=click.Path(exists=True, file_okay=False), required=True)
@click.option("--manifest-file", "-m", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--output-dir", "-o", type=click.Path(file_okay=False), required=True)
@click.option("--recipient-pk", "-r", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--n-cpus", "-t", type=int, default=4)
def encrypt(working_directory, manifest_file, output_dir, recipient_pk, n_cpus):
    if Path(working_directory) == Path(output_dir):
        raise click.ClickException("Working directory and output directory CAN NOT be the same.")       

    manifest = _load_manifest(manifest_file)
    expected_files = set(manifest["file_name"].values)
    to_process = [f for f in _list_files_in_directory(working_directory) if f.name in expected_files]

    if not to_process:
        raise click.ClickException("No files to encrypt.")

    if not Path(output_dir).exists():
        os.makedirs(output_dir, exist_ok=True)
    
    click.echo(f"Encrypting {len(to_process)} files using {n_cpus} process(es)...")

    process_map(
        partial(_encrypt_crypt4gh, recipient_pk=recipient_pk, output_dir=output_dir),
        to_process,
        chunksize=1,
        max_workers=n_cpus,
    )

    click.echo(f"Encryption completed. Encrypted files are saved in {output_dir}.")

@main.command()
@click.option("--working-directory", "-w", type=click.Path(exists=True, file_okay=False), required=True)
@click.option("--output-dir", "-o", type=click.Path(file_okay=False), required=True)
@click.option("--recipient-sk", "-r", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--n-cpus", "-t", type=int, default=4)
def decrypt(working_directory, output_dir, recipient_sk, n_cpus):
    if Path(working_directory) == Path(output_dir):
        raise click.ClickException("Working directory and output directory CAN NOT be the same.")       

    to_process = [f for f in _list_files_in_directory(working_directory) if f.name.endswith(".c4gh")]

    if not to_process:
        raise click.ClickException("No files to decrypt.")

    if not Path(output_dir).exists():
        os.makedirs(output_dir, exist_ok=True)
    
    click.echo(f"Decrypting {len(to_process)} files using {n_cpus} process(es)...")

    process_map(
        partial(_decrypt_crypt4gh, recipient_sk=recipient_sk, output_dir=output_dir),
        to_process,
        chunksize=1,
        max_workers=n_cpus,
    )

    click.echo(f"Decryption completed. Decrypted files are saved in {output_dir}.")
