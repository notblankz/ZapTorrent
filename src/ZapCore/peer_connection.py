import socket
import hashlib
from file_assembler import assemble

def connect_to_peer(peer_ip: str, peer_port: int) -> socket.socket:
    """
    Establishes a TCP connection to the specified IP and port.

    Args:
        peer_ip (str): The IP address of the peer.
        peer_port (int): The port number of the peer.

    Returns:
        socket.socket: The connected socket object.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((peer_ip, peer_port))
    return s
    
  
def perform_handshake(socket: socket.socket, info_hash: bytes, peer_id: bytes) -> bool:
    """
    Performs the BitTorrent handshake with the peer.

    Args:
        socket (socket.socket): The connected socket object.
        info_hash (bytes): The SHA1 hash of the torrent's info dictionary.
        peer_id (bytes): The unique ID of the client.

    Returns:
        bool: True if the handshake was successful, False otherwise.
    """
    handshake = b'\x13BitTorrent protocol' + b'\x00' * 8 + info_hash + peer_id
    socket.send(handshake)
    response = socket.recv(68)
    return response[28:48] == info_hash
    
  
  
  
def send_interested(socket: socket.socket, info_hash: bytes, peer_id: bytes) -> bool:
    """
    Sends an "interested" message to the peer.

    Args:
        socket (socket.socket): The connected socket object.
        info_hash (bytes): The SHA1 hash of the torrent's info dictionary.
        peer_id (bytes): The unique ID of the client.

    Returns:
        bool: True if the message was sent successfully, False otherwise.
    """
    interested_message = b'\x00\x00\x00\x03\x02'  # Message length + interested ID
    socket.send(interested_message)
    response = socket.recv(4)
    return response == b'\x00\x00\x00\x01'
    
  
def receive_bitfield(socket: socket.socket) -> list:
    """
    Receives the bitfield from the peer.

    Args:
        socket (socket.socket): The connected socket object.

    Returns:
        list: A list representing the pieces the peer has.
    """
    response = socket.recv(1024)
    bitfield_length = response[1]
    return list(response[2:2 + bitfield_length])
    
  
def request_piece(socket: socket.socket, piece_index: int, block_offset: int, block_length: int) -> bool:
    """
    Sends a request for a specific piece of data from the peer.

    Args:
        socket (socket.socket): The connected socket object.
        piece_index (int): The index of the piece being requested.
        block_offset (int): The offset within the piece.
        block_length (int): The length of the block being requested.

    Returns:
        bool: True if the request was sent successfully, False otherwise.
    """
    request_message = b'\x00\x00\x00\x0D\x06' + piece_index.to_bytes(4, 'big') + block_offset.to_bytes(4, 'big') + block_length.to_bytes(4, 'big')
    socket.send(request_message)
    response = socket.recv(4)
    return response == b'\x00\x00\x00\x01'
    
  
def receive_piece(socket: socket.socket, piece_index: int, block_offset: int, block_length: int) -> bytes:
    """
    Receives a piece of data from the peer.

    Args:
        socket (socket.socket): The connected socket object.
        piece_index (int): The index of the piece being received.
        block_offset (int): The offset within the piece.
        block_length (int): The length of the block being received.

    Returns:
        bytes: The received piece of data.
    """
    response = socket.recv(block_length + 13)
    return response[13:]
    
  
def download_piece(socket: socket.socket, piece_index: int, block_offset: int, block_length: int) -> bytes:
    """
    Downloads a piece of data from the peer.

    Args:
        socket (socket.socket): The connected socket object.
        piece_index (int): The index of the piece being downloaded.
        block_offset (int): The offset within the piece.
        block_length (int): The length of the block being downloaded.

    Returns:
        bytes: The downloaded piece of data.
    """
    request_piece(socket, piece_index, block_offset, block_length)
    return receive_piece(socket, piece_index, block_offset, block_length)
    

def verify_piece(piece_data: bytes, piece_index: int, info_hash: bytes) -> bool:
    """
    Verifies the integrity of the received piece using SHA1 hash.

    Args:
        piece_data (bytes): The received piece of data.
        piece_index (int): The index of the piece being verified.
        info_hash (bytes): The SHA1 hash of the torrent's info dictionary.

    Returns:
        bool: True if the piece is valid, False otherwise.
    """
    sha1 = hashlib.sha1()
    sha1.update(piece_data)
    return sha1.digest() == info_hash
    
  
def manage_peer_connection(peer_ip: str, peer_port: int, info_hash: bytes, peer_id: bytes, piece_index: int, block_offset: int, block_length: int):
    """
    Manages the connection to a peer and downloads a piece of data.

    Args:
        peer_ip (str): The IP address of the peer.
        peer_port (int): The port number of the peer.
        info_hash (bytes): The SHA1 hash of the torrent's info dictionary.
        peer_id (bytes): The unique ID of the client.
        piece_index (int): The index of the piece being downloaded.
        block_offset (int): The offset within the piece.
        block_length (int): The length of the block being downloaded.

    Returns:
        bool: True if the download was successful, False otherwise.
    """
    socket = connect_to_peer(peer_ip, peer_port)
    if not perform_handshake(socket, info_hash, peer_id):
        return False
    send_interested(socket, info_hash, peer_id)
    bitfield = receive_bitfield(socket)
    if bitfield[piece_index]:
        piece_data = download_piece(socket, piece_index, block_offset, block_length)
        if verify_piece(piece_data, piece_index, info_hash):
            assemble(piece_index, piece_data)
            return True
    return False
    
  
def start_peer_download(peer_ip: str, peer_port: int, info_hash: bytes, peer_id: bytes, piece_index: int, block_offset: int, block_length: int):
    """
    Initiates the download process from a peer.

    Args:
        peer_ip (str): The IP address of the peer.
        peer_port (int): The port number of the peer.
        info_hash (bytes): The SHA1 hash of the torrent's info dictionary.
        peer_id (bytes): The unique ID of the client.
        piece_index (int): The index of the piece being downloaded.
        block_offset (int): The offset within the piece.
        block_length (int): The length of the block being downloaded.

    Returns:
        bool: True if the download was successful, False otherwise.
    """
    return manage_peer_connection(peer_ip, peer_port, info_hash, peer_id, piece_index, block_offset, block_length)
    
  
