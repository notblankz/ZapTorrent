import asyncio
from pathlib import Path
import os

# Global Variables
output_dir = None;
assembly_queue = asyncio.Queue()

def set_output_dir(path: str = None):
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

def assemble_multiple():
    pass # TODO

async def assemble(piece_index: int, piece_data, metadata: dict):
    if b'files' in metadata.get("info"):
        pass # yet to implement
    else:
        file_path = Path(output_dir / ((metadata.get("info"))[b'name']).decode())
        await assembly_queue.put((assemble_single, (piece_index, piece_data, metadata.get("piece length"), file_path)))

async def start_assembler():
    while True:
        func, args = await assembly_queue.get()
        try:
            await asyncio.to_thread(func, *args)
        finally:
            assembly_queue.task_done()
