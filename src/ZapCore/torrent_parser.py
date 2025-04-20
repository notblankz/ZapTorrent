import bencodepy
import hashlib
from pathlib import Path

def parse_torrent(file):
    """
    Parses a .torrent file and returns its metadata.

    Args:
        file (str): The path to the .torrent file.
    """
    try:
        with open(file, "rb") as torrent:
            content = torrent.read()
            decoded_data = bencodepy.bdecode(content)
        print("[PARSER : INFO] Torrent file successfully parsed")

        final_metadata = convert_to_dict(decoded_data)

    except Exception as e:
        print("[PARSER : ERROR] Something went wrong during the parsing of Torrent file")
        print(e)

    return final_metadata

def convert_to_dict(decoded_data:dict):
    """
    Tags the metadata into a dictionary fomat for easier access to variables in the later steps

    Args:
        decoded_data (dict): Raw decoded data from decoding the torrent file
    """
    info = decoded_data.get(b'info', {})
    metadata = {
        "announce" : decoded_data.get(b'announce', "Announce URL not found"),
        "announce-list" : decoded_data.get(b'announce-list', []),
        "comment" : decoded_data.get(b'comment', "No Comments"),
        "created by" : decoded_data.get(b'created by', "No Author"),
        "creation date" : decoded_data.get(b'creation date', "No creation date specified"),
        "piece length" : info.get(b'piece length', 0),
        "piece count" : len(info.get(b'pieces', "No SHA-1 Checksum for pieces found")) // 20,
        "info": info,
        "info hash": hashlib.sha1(bencodepy.bencode(info)).digest(),
        "pieces" : info.get(b'pieces', "No SHA-1 Checksum for pieces found"),
    }
    print("[PARSER : INFO] Converted parsed binary to Dictionary")

    return metadata

def construct_path(raw_path):
    """
    A small helper function in order to create a Path object to put into the lookup table

    Args:
        raw_path (str): Path of the file
    """
    decoded_list = [path.decode() for path in raw_path]
    return Path(*decoded_list)

def construct_lookup_table(metadata: dict):
    """
    This function processes the 'files' list in the torrent metadata to compute
    the absolute byte ranges (start and end) for each file in the torrent. It is used
    to determine which part of a piece corresponds to which file during assembly

    Args:
        metadata (dict): The parsed dictionary of the .torrent file
    """
    try:
        if (metadata.get("info"))[b'files']:
            print("[PARSER : INFO] Creating lookup table for all files")
            global_offset = 0
            file_lookup_table = []
            total_file_size = 0
            for file in ((metadata.get("info"))[b'files']):
                total_file_size += file[b'length']
                start_byte = global_offset
                end_byte = global_offset + file[b'length']
                file_lookup_table.append({"start": start_byte, "end": end_byte, "length": file[b'length'], "path": construct_path(file[b'path'])})
                global_offset += file[b'length']
            print("[PARSER : INFO] Finished creating lookup table")
            metadata["total length"] = total_file_size
            return metadata, file_lookup_table
    except KeyError:
        print("[PARSER : INFO] No need to create lookup table - Single File Torrent")
        metadata["total length"] = (metadata.get("info"))[b'length']
        return metadata, None

def log_lookup_table(lookup_table: list):
    print("[PARSER : LOG] Displaying the created lookup table")
    for i in lookup_table:
        print(i)
    print("[PARSER : LOG] Lookup table display complete")

def log_metadata(metadata):
    """
    Displays the parsed metadata of the torrent file in a readable format.

    Args:
        metadata (dict): The dictionary containing parsed torrent metadata.
    """
    print("[PARSER : LOG] Displaying Torrent Metadata")

    for key, value in metadata.items():
        if key == "announce-list":
            print(f"{key}:")
            for sublist in value:
                print("\t", sublist)
        elif key == "pieces":
            print(f"{key}: (SHA-1 Hashes Hidden for Readability)")
        # Comment the below 2 lines to view the info dictionary
        elif key == "info":
            print(f"{key}: (Entire b'info' field, hidden for Readability)")
        else:
            print(f"{key}: {value}")

    print("[PARSER : LOG] Metadata Display Complete\n")

def get_piece_hash(torrent_metadata, index: int):
    pieces_blob = (torrent_metadata.get('info'))[b'pieces']
    return pieces_blob[index * 20 : (index + 1) * 20]
