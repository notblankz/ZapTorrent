import requests
import random
import urllib
import bencodepy
import socket
import struct
import time

def generate_id():
    """
    Generate a 20 byte peer ID which will give us an identification in the torrent network
    Format: -ZT6969-XXXXXXXXXXXX
    """
    # prefix = b'-ZT6969-'
    prefix = b'-UT3550-'
    suffix = b''
    for _ in range(12):
        char = str(random.randint(0, 9)).encode()
        suffix += char
    peer_ID = prefix + suffix

    print(f"[TRACKER : INFO] Generated our Peer ID : {peer_ID}")

    return peer_ID

def decode_peer_field(peer_bytes):
    """
    The information received of peers from the tracker is in bytes, this function extracts the IP and port from it
    Format:
        4 bytes - IP and 2 bytes - Port (which is why the for loop has 6 as an interval)

    Args:
        peer_bytes (str): The byte object coming from the tracker response
    """
    peers = []

    for i in range(0, len(peer_bytes), 6):
        peer_ip = socket.inet_ntoa(peer_bytes[i:i+4])
        peer_port = struct.unpack(">H", peer_bytes[i+4:i+6])[0]
        peers.append(f"{peer_ip}:{peer_port}")

    return peers

def log_tracker_response(response_dict):
    """
    Logger function to neatly display the tracker response and the Peers

    Args:
        response_dict (dict): Dictionary obtained after decoding and processing the tracker response
    """
    print("[TRACKER : LOG] Displaying Tracker Response")
    print(f"interval : {response_dict['interval']}")
    print(f"min interval : {response_dict['min interval']}")
    print("peers:")

    peers = response_dict['peers']
    for i in range(0, len(peers), 4):
        print("\t".join(peers[i:i+4]))

    print("[TRACKER : LOG] Tracker Response Display Complete\n")

def get_response_udp(tracker_url, info_hash, peer_id, downloaded, left, uploaded, port=6881, num_want=4294967295, event=0):
    """
    Perform a UDP tracker request and return a dictionary with interval and peers list.

    Parameters:
    - tracker_url: str, e.g., 'udp://tracker.opentrackr.org:1337'
    - info_hash: bytes, 20-byte SHA1 hash of the torrent info
    - peer_id: bytes, 20-byte unique ID for this client
    - downloaded: int, total bytes downloaded
    - left: int, bytes left to download
    - uploaded: int, total bytes uploaded
    - port: int, port number this client is listening on
    - num_want: int, number of peers requested (-1 for default)
    - event: int, 0: none; 1: completed; 2: started; 3: stopped

    Returns:
    - dict with keys: 'interval' (int), 'peers' (list of 'IP:port' strings)
    """
    # Parse the tracker URL
    if not tracker_url.startswith("udp://"):
        raise ValueError("Invalid tracker URL. Must start with 'udp://'")
    tracker_url = tracker_url[6:]
    if '/' in tracker_url:
        tracker_url = tracker_url.split('/')[0]
    host, port_str = tracker_url.split(':')
    port = int(port_str)

    # Resolve the hostname to an IP address
    ip = socket.gethostbyname(host)

    # Create a UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)

    # Step 1: Send a connect request
    connection_id = 0x41727101980  # Magic constant
    action = 0  # Connect
    transaction_id = random.randint(0, 0xFFFFFFFF)
    connect_request = struct.pack(">QLL", connection_id, action, transaction_id)
    sock.sendto(connect_request, (ip, port))

    try:
        data, _ = sock.recvfrom(1024)
    except socket.timeout:
        raise ConnectionError("UDP tracker connect request timed out")

    if len(data) < 16:
        raise ValueError("Invalid connect response from tracker")

    resp_action, resp_transaction_id, new_connection_id = struct.unpack(">LLQ", data[:16])
    if resp_transaction_id != transaction_id or resp_action != 0:
        raise ValueError("UDP tracker connect response mismatch")

    # Step 2: Send an announce request
    transaction_id = random.randint(0, 0xFFFFFFFF)
    key = random.randint(0, 0xFFFFFFFF)
    announce_request = struct.pack(
        ">QLL20s20sQQQLLLLH",
        new_connection_id,  # connection ID
        1,                  # action (announce)
        transaction_id,
        info_hash,
        peer_id,
        downloaded,
        left,
        uploaded,
        event,
        0,                  # IP address (default)
        key,
        num_want,
        port
    )
    sock.sendto(announce_request, (ip, port))

    try:
        data, _ = sock.recvfrom(4096)
    except socket.timeout:
        raise ConnectionError("UDP tracker announce request timed out")

    if len(data) < 20:
        raise ValueError("Invalid announce response from tracker")

    resp_action, resp_transaction_id, interval, leechers, seeders = struct.unpack(">LLLLL", data[:20])
    if resp_transaction_id != transaction_id or resp_action != 1:
        raise ValueError("UDP tracker announce response mismatch")

    peers = []
    offset = 20
    while offset + 6 <= len(data):
        ip_bytes = data[offset:offset+4]
        port_bytes = data[offset+4:offset+6]
        ip_str = socket.inet_ntoa(ip_bytes)
        port_num = struct.unpack(">H", port_bytes)[0]
        peers.append(f"{ip_str}:{port_num}")
        offset += 6

    print("[TRACKER : INFO] Tracker Request successful, received all peers available")

    return {
        "interval": interval,
        "peers": peers
    }


def get_response_http(request_url: str):
    response = requests.get(request_url, timeout=20)
    response.raise_for_status() # Raises an HTTPError if anything did go wrong in the HTTP side of things
    decoded_resp = bencodepy.bdecode(response.content)
    print("[TRACKER : INFO] Tracker Request successful, received all peers available")
    return {
        "interval" : decoded_resp.get(b'interval'),
        "min interval" : decoded_resp.get(b'min interval'),
        "peers" : decode_peer_field(decoded_resp.get(b'peers'))
    }

def get_peers(metadata:dict, peer_id, max_retries: int, retry_delay: int):
    """
    Sends a GET request to the tracker to retrieve a list of peers participating in the torrent.

    This function constructs a request URL using the provided metadata and peer_id,
    then contacts the tracker to fetch peer information. The response is decoded from the
    bencoded format and returned as a dictionary containing:

    - interval: The interval (in seconds) before the client should re-request peers.
    - min interval: The minimum allowed interval for requesting peers.
    - peers: A list of decoded (IP, port) tuples representing available peers.

    Args:
        metadata (dict): The parsed metadata of the .torrent file
        peer_id (bytes): The unique peer ID used to identify this client in the network.
    """
    info_hash = metadata.get("info hash")
    port = random.randint(6881, 6889)
    uploaded = 0
    downloaded = 0
    left = 0

    if b'files' in metadata["info"]:
        for i in metadata["info"][b'files']:
            left = sum(file[b'length'] for file in metadata["info"][b'files'])
    else:
        left = metadata["info"][b'length']

    req_params = {
        "info_hash": info_hash,
        "peer_id": peer_id,
        "port": port,
        "downloaded": downloaded,
        "uploaded": uploaded,
        "left": left,
        "compact" : 1
    }

    trackers = []
    if "announce" in metadata:
        trackers.append((metadata["announce"]).decode())

    if "announce-list" in metadata:
        for url_list in metadata["announce-list"]:
            for url in url_list:
                decoded_url = url.decode()
                if decoded_url:
                    trackers.append(decoded_url)

    encoded_params = urllib.parse.urlencode(req_params, safe=":/")


    for tracker in trackers:
        request_url = f"{tracker}?{encoded_params}"
        for attempt in range(1, max_retries + 1):
            print(f"[TRACKER : INFO] Sending Request to {tracker} for Peer list -> Attempt {attempt}")

            try:
                if tracker.startswith("udp://"):
                    response = get_response_udp(tracker, info_hash, peer_id, downloaded, left, uploaded, port)
                    # print("[TRACKER : INFO] Have not implement udp tracker request skipping it for now")
                    # continue
                else:
                    response = get_response_http(request_url)
                return response
            except Exception as e:
                print("[TRACKER : ERROR] Tracker request failed")
                print(e)
                if attempt < max_retries:
                    print(f"[TRACKER : INFO] Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    print(f"[TRACKER : ERROR] Failed to get peers from {tracker} - Tried {attempt} times")
                    break
    else:
        print("[TRACKER : ERROR] Did not get a response from any tracker URL")
        exit()
