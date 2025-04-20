import ZapCore.torrent_parser as Parser
import ZapCore.tracker_request as Request
import ZapCore.file_assembler as Assembler
import ZapCore.peer_connection as PeerConnector
import argparse
from pathlib import Path
import asyncio
import traceback

async def main():
    parser = argparse.ArgumentParser(
        description="ZapTorrent - A CLI based torrent client",
        usage="\n  zap --parse <path to .torrent file>"
              "\n  zap --download <path to .torrent file>",
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable detailed logging")
    parser.add_argument("--parse", "-p", metavar="<path to .torrent file>", type=str, help="Parse and display metadata of the given .torrent file.")
    parser.add_argument("--download", "-d", metavar="<path to .torrent file>", type=str, help="Download files using the BitTorrent protocol.")
    parser.add_argument("--output", "-o", metavar="<download destination>", type=str, default=str(Path(__file__).resolve().parents[1] / "Downloads"), help="Specify where to save downloaded files.")

    args = parser.parse_args()
    Assembler.set_output_dir(args.output)

    # Start assembler consumer
    asyncio.create_task(Assembler.start_assembler())

    if args.download:
        torrent_metadata = Parser.parse_torrent(args.download)
        if args.verbose: Parser.log_metadata(torrent_metadata)

        file_lookup = Parser.construct_lookup_table(torrent_metadata)
        if args.verbose: Parser.log_lookup_table(file_lookup)
        Assembler.set_global_variables(torrent_metadata, file_lookup)

        peer_id = Request.generate_id()

        try:
            tracker_response = Request.get_peers(torrent_metadata, peer_id, 3, 3)
        except ConnectionError as e:
            print(f"[MAIN] Tracker error: {str(e)}")
            return

        if args.verbose: Request.log_tracker_response(tracker_response)

        peers = tracker_response.get("peers", [])
        total_pieces = torrent_metadata.get("piece count")

        for piece_index in range(0, total_pieces):
            print(f"[DOWNLOADER : INFO] Downloading piece {piece_index}/{total_pieces - 1}")
            piece_hash = Parser.get_piece_hash(torrent_metadata, piece_index)

            piece_downloaded = False
            
            for peer in peers:
                try:
                    ip, port = peer.split(":")
                    piece_data = await PeerConnector.download_piece(
                        peer_ip=ip,
                        peer_port=int(port),
                        info_hash=torrent_metadata["info hash"],
                        peer_id=peer_id,
                        piece_index=piece_index,
                        piece_length=torrent_metadata["piece length"],
                        expected_hash=Parser.get_piece_hash(torrent_metadata, piece_index)
                    )

                    if piece_data:
                        print(f"[DOWNLOADER : OK] Downloaded piece {piece_index}")
                        await Assembler.assemble(piece_index, piece_data)

                        # Move working peer to front for priority in next piece
                        peers.remove(peer)
                        peers.insert(0, peer)
                        piece_downloaded = True
                        break

                except Exception:
                    print(f"[DOWNLOADER : WARN] Failed to get piece {piece_index} from {peer}")
                    print(traceback.format_exc())

            if not piece_downloaded:
                print(f"[DOWNLOADER : FAIL] Could not download piece {piece_index} from any peer.")

        await Assembler.assembly_queue.join()
        print("[MAIN] All pieces processed.")

    elif args.parse:
        torrent_metadata = Parser.parse_torrent(args.parse)
        Parser.log_metadata(torrent_metadata)
        file_lookup = Parser.construct_lookup_table(torrent_metadata)
        peer_id = Request.generate_id()
        tracker_response = Request.get_peers(torrent_metadata, peer_id, 3, 3)
        print(tracker_response.get("peers"))

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDownload interrupted by user")
    except Exception as e:
        print(f"Fatal error: {str(e)}")
