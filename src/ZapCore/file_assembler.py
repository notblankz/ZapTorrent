import asyncio
from pathlib import Path
import os
import bisect

# Global Variables
output_dir = None;
assembly_queue = asyncio.Queue()
metadata = {}
file_lookup_table = []
file_ends_list = []

def set_global_variables(torrent_metadata, lookup_table):
    """
    This function helps extract the metadata and the lookup table from main.py in order to remove redundancy

    Args:
        torrent_metadata (dict): The parsed metadata of the torrent
        lookup_table (list): A list of dictionaries, each being a file from a multifile torrent
    """
    global metadata, file_lookup_table, file_ends_list
    metadata = torrent_metadata
    if lookup_table:
        file_lookup_table = lookup_table
        file_ends_list = [file["end"] for file in file_lookup_table]

def set_output_dir(path: str = None):
    """
    This function takes the output directory (if specified) in the run command by the user otherwise sets the value to the
    default directory

    Args:
        path (str): The path string of the output directory set by the user
    """
    global output_dir
    if path:
        output_dir = Path(path)
    else:
        output_dir = Path((os.path.abspath(Path(__file__).resolve().parents[1] / "Downloads")))

def assemble_single(piece_index:int, piece_data, piece_length:int, file_path:str):
    """
    This function ensures that the received piece is written at the correct offset within the single-file torrent.

    Args:
        piece_index (int): The index of the piece being written.
        piece_data (bytes): The binary data of the received piece.
        piece_length (int): The size of each piece in bytes.
        file_path (str): The path to the output file.
    """
    os.makedirs(Path(file_path).parent, exist_ok=True)

    try:
        with open(file_path, "a+b") as f:
            f.seek(piece_index * piece_length)
            f.write(piece_data)
            print(f"[ASSEMBLER : INFO] Successfully written Piece Index: {piece_index}")
    except Exception as e:
        print(f"[ASSEMBLER : ERROR] Some error occured when trying to write Piece Index: {piece_index}")
        print(f"[ASSEMBLER : ERROR] Retrying to write Piece Index: {piece_index}")
        print(e)

def assemble_multiple(piece_index: int, piece_data, piece_length: int):
    """
    Assembles and writes a given piece of data across multiple files in a multi-file torrent.

    Args:
        piece_index (int): The index of the piece being written.
        piece_data (bytes): The binary data of the received piece.
        piece_length (int): The size of each piece in bytes.
    """
    bytes_written = 0
    piece_start = piece_index * piece_length
    piece_end = piece_start + len(piece_data)

    idx = bisect.bisect_left(file_ends_list, piece_start)

    print(f"[ASSEMBLER : INFO] Starting write for Piece Index: {piece_index} (Range: {piece_start}-{piece_end})")

    for file in file_lookup_table[idx:]:
        if file["start"] >= piece_end:
            break

        if file["end"] <= piece_start:
            continue

        overlap_start = max(file["start"], piece_start)
        overlap_end = min(file["end"], piece_end)
        overlap_len = overlap_end - overlap_start

        remaining_file_bytes = file["length"] - (overlap_start - file["start"])
        write_len = min(overlap_len, remaining_file_bytes)

        if write_len <= 0:
            continue

        os.makedirs(Path(output_dir / file["path"].parent), exist_ok=True)
        file_path = Path(output_dir / file["path"])

        if not file_path.exists():
            with open(file_path, "wb") as f:
                f.truncate(file["length"])

        try:
            with open(Path(output_dir / file["path"]), "r+b") as f:
                f.seek(overlap_start - file["start"])
                f.write(piece_data[(overlap_start - piece_start): (overlap_start - piece_start) + write_len])
                bytes_written += write_len
                print(f"[ASSEMBLER : INFO] Wrote {write_len} bytes to {file['path']} at offset {overlap_start - file['start']}")
        except Exception as e:
            print(f"[ASSEMBLER : ERROR] Failed to write to file: {file['path']} for Piece Index: {piece_index}")
            print(f"[ASSEMBLER : ERROR] {e}")
        if bytes_written >= piece_length:
            print(f"[ASSEMBLER : INFO] Finished writing Piece Index: {piece_index}")
            break


async def assemble(piece_index: int, piece_data):
    """
    Checks if the file being given for assembly is a multi-file torrent or a single-file torrent and then adds the specific
    assembly function to the assembly queue for it to be processes

    Args:
        piece_index (int): Index of the piece that has to be written
        piece_data (binary): Actual piece data in binary coded format
        metadata (dict): The parsed torrent metadata in the form of a dictionary
    """
    if b'files' in metadata.get("info"):
        await assembly_queue.put((assemble_multiple, (piece_index, piece_data, metadata.get("piece length"))))
    else:
        file_path = Path(output_dir / ((metadata.get("info"))[b'name']).decode())
        await assembly_queue.put((assemble_single, (piece_index, piece_data, metadata.get("piece length"), file_path)))

async def start_assembler():
    """
    Creates a infinite loop that pops one assembly process from the queue and dispatches it into a new thread to process
    the assembly
    """
    while True:
        func, args = await assembly_queue.get()
        try:
            await asyncio.to_thread(func, *args)
        finally:
            assembly_queue.task_done()
