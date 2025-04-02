import os
from pathlib import Path

def get_default_path():
    return (os.path.abspath(Path(__file__).resolve().parents[1] / "Downloads"))

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
            print(f"[INFO] Successfully written Piece Index: {piece_index}")
    except Exception as e:
        print(f"[ERROR] Some error occured when trying to write Piece Index: {piece_index}")
        print(e)

def assemble_multiple(piece_index:int, piece_data, piece_length:int, metadata:dict, file_path:str):
    pass

def assemble(piece_index:int, piece_data, metadata:dict, output_directory: str = None):
    """
    Determines whether the torrent is a single-file or multi-file torrent and calls the appropriate function.

    Args:
        piece_index (int): The index of the piece being written.
        piece_data (bytes): The binary data of the received piece.
        metadata (dict): The parsed metadata of the torrent file.
        output_directory (str): The directory where the files will be saved.
    """
    if output_directory is None:
        output_directory = get_default_path()

    output_directory = Path(output_directory)

    if b'files' in metadata.get("info"):
        file_path = output_directory / (metadata.get("info")[b'name']).decode()
        assemble_multiple(piece_index, piece_data, metadata.get('piece length'), metadata, file_path)
    else:
        file_path = output_directory / metadata.get("info")[b'name'].decode()
        assemble_single(piece_index, piece_data, metadata.get('piece length'), file_path)
