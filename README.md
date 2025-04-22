# ⚡ ZapTorrent (Work in progress)

**ZapTorrent** is a high-performance, command-line BitTorrent client written in Python. It allows users to:

- Parse `.torrent` metadata
- Retrieve peer lists from trackers
- Download files piece-by-piece using the BitTorrent protocol

ZapTorrent is designed for efficiency and includes features to optimize peer selection and download throughput.


## Performance Optimization Used (in [main.py](/src/main.py))
<img src = "/extras/optimization.webp">

- Parallel download workers choose a peer and piece to download.
- If a peer responds successfully, it’s moved to the front of the queue (preferred).
- If a peer fails, it's sent to the back of the queue (penalized).
- Failed downloads are retried by a dedicated **Failed Piece Worker Pool** using an **end-game strategy** — request from all peers and cancel others when one succeeds.
- If a piece still fails, it's added back for future retry.

## Future Feature Implementations:
- Connection pooling for better peer reuse
- Periodic tracker refresh to discover new peers
- Support for **UDP tracker requests**

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

## License

This project is open-source and available under the MIT License.
