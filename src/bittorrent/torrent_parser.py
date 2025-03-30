import bencodepy


def parseTorrent(file):
    """
    Parses a .torrent file and returns its metadata.

    Args:
        file (str): The path to the .torrent file.
    """
    try:
        with open(file, "rb") as torrent:
            content = torrent.read()
            decoded_data = bencodepy.bdecode(content)
        print("[INFO] Torrent file successfully parsed")

        final_metadata = convertToDict(decoded_data)

    except Exception as e:
        print("[ERROR] Something went wrong during the parsing of Torrent file")
        print(e)

    return final_metadata

def convertToDict(decoded_data:dict):
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
        "files" : info.get(b'files', "No file list found"),
        "name" : info.get(b'name', "No name to the final file"),
        "piece length" : info.get(b'piece length', 0),
        "piece count" : len(info.get(b'pieces', "No SHA-1 Checksum for pieces found")) // 20,
        "pieces" : info.get(b'pieces', "No SHA-1 Checksum for pieces found")
    }
    print("[INFO] Converted parsed binary to Dictionary")

    return metadata

def displayAttributes(metadata):
    """
    Displays the parsed metadata of the torrent file in a readable format.

    Args:
        metadata (dict): The dictionary containing parsed torrent metadata.
    """
    print("[INFO] Displaying Torrent Metadata\n")

    for key, value in metadata.items():
        if key == "files" and isinstance(value, list):
            print(f"{key}:")
            for file in value:
                print("\t",file)
        elif key == "announce-list":
            print(f"{key}:")
            for sublist in value:
                print("\t", sublist)
        elif key == "pieces":
            print(f"{key}: (SHA-1 Hashes Hidden for Readability)")
        else:
            print(f"{key}: {value}")

    print("\n[INFO] Metadata Display Complete\n")
