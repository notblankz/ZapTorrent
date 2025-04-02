import ZapCore.torrent_parser as Parser
import ZapCore.tracker_request as Request
import ZapCore.file_assembler as Assemble
import argparse
from pathlib import Path

def main():

    parser = argparse.ArgumentParser(
        description="ZapTorrent - A CLI based torrent client",
        usage="\n  zap --parse <path to .torrent file>"
              "\n  zap --download <path to .torrent file>",
        )

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable detailed logging")
    parser.add_argument("--parse", "-p", metavar="<path to .torrent file>" ,type=str, help="Parse and display metadata of the given .torrent file, including file details and tracker URLs.")
    parser.add_argument("--download", "-d", metavar="<path to .torrent file>", type=str, help="Start downloading files from the given .torrent file using the BitTorrent protocol")
    parser.add_argument("--output", "-o", metavar="<download destination>", type=str, default=str(Path(__file__).resolve().parents[1] / "Downloads"), help="Specify the directory where the downloaded files should be saved.")

    args = parser.parse_args()

    if args.download:
        torrent_metadata = Parser.parse_torrent(args.download)
        if args.verbose: Parser.log_metadata(torrent_metadata)
        peer_id = Request.generate_id()
        tracker_response = Request.get_peers(torrent_metadata, peer_id)
        if args.verbose: Request.log_tracker_response(tracker_response)
    elif args.parse:
        torrent_metadata = Parser.parse_torrent(args.parse)
        Parser.log_metadata(torrent_metadata)

if __name__ == "__main__":
    main()
