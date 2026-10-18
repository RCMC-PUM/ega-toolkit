# EGA Toolkit
![Static Badge](https://img.shields.io/badge/Python-3.13-blue)
![GitHub License](https://img.shields.io/github/license/RCMC-PUM/ega-toolkit)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)


A simple CLI for preparing genomic data for the **European Genome-phenome Archive (EGA)**: generate checksum manifests, validate files, and encrypt or decrypt data using **Crypt4GH**.

## What is EGA, and why encrypt data?

The [European Genome-phenome Archive (EGA)](https://ega-archive.org/) stores and provides controlled access to human genomic and phenotypic data. Files such as BAMs and FASTQs can contain sensitive, potentially identifiable information, so they must be protected when shared.

The toolkit uses **Crypt4GH envelope encryption**:

1. A temporary **symmetric key** encrypts the file contents efficiently.
2. The symmetric key is protected using the **recipient's (EGA/FEGA) public key** and stored in the encrypted file's header.
3. Only recipient (in this case EGA/FEGS) with a **matching private key** can recover the symmetric key and decrypt the file.

This combines fast encryption for large files with public-key-based access control. **For EGA submission, use the public key specified by EGA/FEGA.** 

## Install

Requires **Python >=3.13** and Git.

```bash
git clone https://github.com/RCMC-PUM/ega-toolkit.git && cd ega-toolkit
python -m pip install poetry && poetry install .
```

Check the installation:

```bash
ega-toolkit --help
```

## 1. Create a manifest

Put the files you want to process in one directory, for example `data/`. The command computes **MD5 checksums** and writes `data/manifest.csv` with `file_name` and `checksum` columns.

```bash
ega-toolkit create-manifest -w data/ -t 4
```

## 2. Check files against the manifest

Recompute checksums and compare them with the manifest:

```bash
ega-toolkit check -w data/ -m data/manifest.csv -t 4
```

Open `data/manifest_validation_report.csv`. The **`checksum_match`** column should be `True` for every checked file. Review the report before encrypting, the command produces a report rather than automatically stopping on a mismatch.

## 3. Encrypt files

Download or obtain the **recipient's Crypt4GH public key** (for EGA/FEGA submissions, the key EGA/FEGA instructs you to use). The toolkit encrypts the files present in wokring directory and listed in the manifest and writes `.c4gh` files to a separate output directory.

```bash
ega-toolkit encrypt -w data/ -m data/manifest.csv -o encrypted/ -r recipient.pub -t 4
```

**Note:** `encrypt` uses the manifest to select files; it does **not** itself check whether their current checksums match. Run step 2 first.

## 4. Decrypt files

Decryption requires the **private key matching the public key used for encryption**. In particular, you cannot decrypt data encrypted solely for EGA/FEGA using an unrelated private key.

```bash
ega-toolkit decrypt -w encrypted/ -o decrypted/ -r recipient.sec -t 4
```

The decrypted files are written to `decrypted/`.

## Performance and progress

- **Multiprocessing:** Use `-t` / `--n-cpus` to set the number of worker processes (default: **4**). Multiple files can be processed in parallel.
- **Progress monitoring:** A `tqdm` progress bar shows how many files have finished during manifest creation, validation, encryption, and decryption.
- **Example benchmark:** Checksumming a **>120 GB BAM file took approximately 2 minutes on a Mac Pro**. Actual speeds depend on storage performance, CPU, and other workloads.
- **Important:** Each file is handled by one worker. Increasing `-t` helps when processing **multiple files**, but does not split one BAM across workers. The progress bar tracks **files**, not bytes within a file.

To see all options:

```bash
ega-toolkit create-manifest --help
ega-toolkit check --help
ega-toolkit encrypt --help
ega-toolkit decrypt --help
```
