import ZapCore.torrent_parser as Parser
import ZapCore.tracker_request as Request
import ZapCore.file_assembler as Assembler
import ZapCore.peer_connection as PeerConnector
import argparse
from pathlib import Path
import asyncio
from collections import deque
import time
from tqdm import tqdm
import math
import sys

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

    logfile = open(f"{Path(args.download).name}.log", "w")
    sys.stdout = logfile

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

        pbar = tqdm(
            desc="Download Progress",
            total=torrent_metadata.get("piece count"),
            bar_format='[{elapsed}] [{n_fmt}/{total_fmt}] |{bar}| {percentage: 3.0f}%',
            position=0,
            leave=True,
            colour='cyan',
        )

        peer_deque = deque(tracker_response.get("peers"))
        peer_deque_lock = asyncio.Lock()
        piece_queue = asyncio.Queue()
        failed_piece_queue = asyncio.Queue()

        for piece in range(0, torrent_metadata.get("piece count")):
            await piece_queue.put(piece)

        async def download_worker(worker_id):
            try:
                while not piece_queue.empty():
                    piece_index = await piece_queue.get()
                    tried_peers = 0
                    success = False
                    max_retries = min(math.ceil(len(tracker_response.get("peers"))/2), 10)
                    while tried_peers < max_retries:
                        peer = None
                        async with peer_deque_lock:
                            if peer_deque:
                                peer = peer_deque.popleft()
                        if not peer:
                            await asyncio.sleep(0.5)
                            continue
                        ip, port = peer.split(":")
                        print(f"[DOWNLOADER : WORKER {worker_id}] Starting Download -> Peer: {peer} and Piece Index: {piece_index}")
                        try:
                            recv_piece_data = await PeerConnector.download_piece(
                            ip, port,
                            torrent_metadata.get("info hash"),
                            peer_id, piece_index,
                            torrent_metadata.get("piece length"),
                            Parser.get_piece_hash(torrent_metadata, piece_index),
                            torrent_metadata)
                            if recv_piece_data:
                                async with peer_deque_lock:
                                    peer_deque.appendleft(peer)
                                await Assembler.assemble(piece_index, recv_piece_data)
                                success = True
                                print(f"[DOWNLOADER : WORKER {worker_id}] Finished Download -> Peer: {peer} and Piece Index: {piece_index}")
                                pbar.update(1)
                                break
                            else:
                                async with peer_deque_lock:
                                    peer_deque.append(peer)
                                if tried_peers < max_retries - 1:
                                    print(f"[DOWNLOADER : WORKER {worker_id}] Retrying Download -> Peer: {peer} and Piece Index: {piece_index}")
                        except Exception as e:
                            async with peer_deque_lock:
                                peer_deque.append(peer)
                        tried_peers += 1
                    if not success:
                        print(f"[DOWNLOADER : WORKER {worker_id}] Failed Download -> Peer: {peer} and Piece Index: {piece_index}")
                        print(f"[DOWNLOADER : WORKER {worker_id}] Adding Piece {piece_index} to Failed Piece Queue")
                        await failed_piece_queue.put(piece_index)
                    piece_queue.task_done()
            finally:
                print(f"[DOWNLOADER : WORKER {worker_id}] Shut Down")

        async def failed_piece_worker(worker_id):
            while True:
                try:
                    piece_index = await failed_piece_queue.get()
                    success = False
                    try:
                        for peer in tracker_response.get("peers"):
                            try:
                                print(f"(Failed Piece Queue: {list(failed_piece_queue._queue)})[FAILED : WORKER {worker_id}] Retrying Failed Piece -> Peer: {peer} and Piece Index: {piece_index}")
                                ip, port = peer.split(":")

                                recv_piece_data = await PeerConnector.download_piece(
                                    ip, port,
                                    torrent_metadata.get("info hash"),
                                    peer_id, piece_index,
                                    torrent_metadata.get("piece length"),
                                    Parser.get_piece_hash(torrent_metadata, piece_index),
                                    torrent_metadata
                                )
                                if recv_piece_data:
                                    async with peer_deque_lock:
                                        peer_deque.appendleft(peer)
                                    await Assembler.assemble(piece_index, recv_piece_data)
                                    pbar.update(1)
                                    print(f"(Failed Piece Queue: {list(failed_piece_queue._queue)})[FAILED : WORKER {worker_id}] Recovered Failed Piece -> Peer: {peer} and Piece Index: {piece_index}")
                                    success = True
                                    break
                            except Exception as e:
                                print(f"(Failed Piece Queue: {list(failed_piece_queue._queue)})[FAILED : WORKER {worker_id}] Error in Recovering Piece -> Peer: {peer} and Piece Index: {piece_index}")
                    finally:
                        if not success:
                            print(f"(Failed Piece Queue: {list(failed_piece_queue._queue)})[FAILED : WORKER {worker_id}] Could no Recover Piece, Adding Piece {piece_index} back to Failed Piece Queue")
                            await asyncio.sleep(1)
                            await failed_piece_queue.put(piece_index)
                        failed_piece_queue.task_done()
                except asyncio.CancelledError:
                    print(f"[FAILED : WORKER {worker_id}] Shut Down")
                    break
                except Exception as e:
                    print(f"[FAILED : WORKER {worker_id}] Critical error: {str(e)}")
                    failed_piece_queue.task_done()

        download_worker_array = [asyncio.create_task(download_worker(worker_id)) for worker_id in range(1, 21)]
        failed_piece_worker_array = [asyncio.create_task(failed_piece_worker(worker_id)) for worker_id in range(101, 121)]


        try:
            await piece_queue.join()
            await failed_piece_queue.join()
            await Assembler.assembly_queue.join()
        finally:
            for worker in failed_piece_worker_array + download_worker_array:
                worker.cancel()

            await asyncio.gather(
                *download_worker_array,
                *failed_piece_worker_array,
                return_exceptions=True
            )

        pbar.close()

        duration = time.time() - start_time
        hours, rem = divmod(duration, 3600)
        minutes, seconds = divmod(rem, 60)
        print(f"\nCompleted download in {int(hours)}h {int(minutes)}m {seconds:.2f}s")

    elif args.parse:
        torrent_metadata = Parser.parse_torrent(args.parse)
        Parser.log_metadata(torrent_metadata)
        torrent_metadata, file_lookup = Parser.construct_lookup_table(torrent_metadata)
        if args.verbose and (b'files' in torrent_metadata.get("info")): Parser.log_lookup_table(file_lookup)
        peer_id = Request.generate_id()
        tracker_response = Request.get_peers(torrent_metadata, peer_id, 3, 3)
        print(tracker_response.get("peers"))

if __name__ == "__main__":
    asyncio.run(main())
