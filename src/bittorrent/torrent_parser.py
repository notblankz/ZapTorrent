import bencodepy


def parseTorrent(file):
    """
    Parses a .torrent file and returns its metadata.

    This function reads a .torrent file, decodes the bencoded content,
    and prints each attribute along with its value.

    Args:
        file (str): The path to the .torrent file.
    """
    with open(file, "rb") as torrent:
        content = torrent.read()
        torrent_attrib = bencodepy.bdecode(content)

    return torrent_attrib
