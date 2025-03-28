from bittorrent.torrent_parser import parseTorrent

def main():
    torrent_attrib = parseTorrent("../tests/Balatro.torrent")
    for ele in torrent_attrib:
        print(torrent_attrib[ele])
        print("\n")

if __name__ == "__main__":
    main()
