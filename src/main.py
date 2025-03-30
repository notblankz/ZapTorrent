import ZapCore.torrent_parser as Parser
import ZapCore.tracker_request as Request

def main():
    torrent_metadata = Parser.parse_torrent("../tests/Balatro.torrent")
    Parser.log_metadata(torrent_metadata)
    peer_id = Request.generate_id()
    tracker_response = Request.get_peers(torrent_metadata, peer_id)
    Request.log_tracker_response(tracker_response)

if __name__ == "__main__":
    main()
