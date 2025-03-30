import ZapCore.torrent_parser as Parser

def main():
    torrent_attrib = Parser.parseTorrent("../tests/Balatro.torrent")
    Parser.displayAttributes(torrent_attrib)


if __name__ == "__main__":
    main()
