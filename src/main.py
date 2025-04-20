import ZapCore.torrent_parser as Parser
import ZapCore.tracker_request as Request
import ZapCore.file_assembler as Assembler
import ZapCore.peer_connection as PeerConnector
import argparse
from pathlib import Path
import asyncio
from collections import deque
import time

# temp
import traceback
import sys

logfile = open('output_log_2.txt', 'w', encoding="utf-8")
sys.stdout = logfile

async def main():

    start_time = time.time()

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
    Assembler.set_output_dir(args.output)

    asyncio.create_task(Assembler.start_assembler())

    if args.download:
        torrent_metadata = Parser.parse_torrent(args.download)
        if args.verbose: Parser.log_metadata(torrent_metadata)
        torrent_metadata, file_lookup = Parser.construct_lookup_table(torrent_metadata)
        if args.verbose and (b'files' in torrent_metadata.get("info")): Parser.log_lookup_table(file_lookup)
        Assembler.set_global_variables(torrent_metadata, file_lookup)
        peer_id = Request.generate_id()
        tracker_response = Request.get_peers(torrent_metadata, peer_id, 3, 3)
        if args.verbose: Request.log_tracker_response(tracker_response)

        for piece_index in range(0,5):
            print(f"[DOWNLOADER : INFO] Download piece {piece_index}/{torrent_metadata.get("piece count") - 1}")

            try:
                for peer in tracker_response.get("peers"):
                    ip, port = peer.split(":")
                    if ip and port:
                        # recv_piece_data = PeerConnector.start_peer_download(ip, int(port), torrent_metadata.get("info hash"), peer_id, piece_index, Parser.get_piece_hash(torrent_metadata, piece_index))
                        recv_piece_data = await asyncio.to_thread(
                            PeerConnector.start_peer_download,
                            ip,
                            int(port),
                            torrent_metadata.get("info hash"),
                            peer_id,
                            piece_index,
                            Parser.get_piece_hash(torrent_metadata, piece_index)
                        )
                        if recv_piece_data != None:
                            # bump the peer to the top of the list for subsequent requests
                            (tracker_response.get("peers")).remove(peer)
                            (tracker_response.get("peers")).insert(0, peer)
                            print(f"[DOWNLOADER : INFO] Successfully downloaded piece {piece_index}/{torrent_metadata.get("piece count") - 1}")
                            await Assembler.assemble(piece_index, recv_piece_data)
                            break
            except Exception as e:
                print("Error in main.py")
                print(traceback.format_exc())

        await Assembler.assembly_queue.join()



    elif args.parse:
        torrent_metadata = Parser.parse_torrent(args.parse)
        # Parser.log_metadata(torrent_metadata)
        torrent_metadata, file_lookup = Parser.construct_lookup_table(torrent_metadata)
        if args.verbose and (b'files' in torrent_metadata.get("info")): Parser.log_lookup_table(file_lookup)
        peer_id = Request.generate_id()
        tracker_response = Request.get_peers(torrent_metadata, peer_id, 3, 3)
        # print(tracker_response.get("peers"))

if __name__ == "__main__":
    asyncio.run(main())
