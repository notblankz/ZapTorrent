# ⚡ ZapTorrent (Work in progress)

ZapTorrent is a command-line torrent client that allows users to parse torrent metadata, retrieve peer lists, and start downloading files using the BitTorrent protocol.

## Prerequisites

Ensure you have Python installed (preferably Python 3.8+).

Install required dependencies:

```sh
pip install -r requirements.txt
```

## Usage

Run the following command to see available options:

```sh
python src/main.py --help
```

### Parsing a Torrent File

To parse and display metadata of a `.torrent` file, including file details and tracker URLs:

```sh
python src/main.py --parse <path_to_torrent_file>
```

Example:

```sh
python src/main.py --parse ubuntu.torrent
```

### Downloading a Torrent File

To start downloading the file(s) from a torrent:

```sh
python src/main.py --download <path_to_torrent_file> [--output <download_directory>] [--verbose]
```

- `--output` (optional): Specify the directory where the files should be saved. Defaults to `Downloads` at the project root.

- `--verbose` (optional): Enables detailed logging for debugging and tracking download progress.


Example:

```sh
python src/main.py --download ubuntu.torrent --output /home/user/Downloads --verbose
```

## Features Implemented So Far

- Parsing `.torrent` files to extract metadata.

- Retrieving peer lists from trackers.

- Basic single-file assembly for downloads.

- Command-line options for parsing, downloading, and specifying output directories.

- Verbose logging support.


## Roadmap

- Implementing multi-file torrent support.

- Handling peer communication and piece exchange.

- Adding error handling and performance optimizations.


## License

This project is open-source and available under the MIT License.
