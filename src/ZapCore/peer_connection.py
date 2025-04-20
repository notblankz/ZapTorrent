import asyncio
import struct
import hashlib
import traceback

async def connect(ip: str, port: int):
    """
    This function makes a TCP connection to the peer's ip and port and wraps it in a async byte stream reader and writer
    so that we can directly read from and write to the peer using reader and writer Stream object respectively while being
    in an async environment

    Args:
        ip: IP of the peer you want to connect to
        port: the port exposed by the peer for us to make a connection to
    """
    reader, writer = await asyncio.open_connection(ip, port)
    return reader, writer

async def handshake(reader, writer, info_hash: bytes, peer_id: bytes):
    """
    This is the first step in bittorrent protocol, it makes sure that both the End Systems know they have to communicate in
    bittorrent protocol

    Sent Message:
    handshake: <pstrlen><pstr><reserved><info_hash><peer_id>

    Received Message:
    handshake: <pstrlen><pstr><reserved><info_hash><peer_id>

    Args:
        reader: Reader object with the peer
        Writer: Writer object with the peer
        info_hash: SHA1 hash of the entire metadata which uniquely identifies the torrent we want to download
        peer_id: Our own generated peer id
    """
    pstr = b"BitTorrent protocol"
    pstrlen = len(pstr)
    reserved = b"\x00" * 8
    handshake_message = struct.pack(">B19s8s20s20s", pstrlen, pstr, reserved, info_hash, peer_id)

    writer.write(handshake_message)
    await writer.drain()

    response = await reader.read(68)

    if (len(response) < 68): print("[HANDSHAKE : FAILED] Received incorrect handshake response")

    received_info_hash = response[28:48]
    if received_info_hash == info_hash:
        return True

    return False

async def send_interested(writer):
    """
    This function sends an 'interested' message to the peer, which is part of the BitTorrent protocol
    it tells the peer that we are interested in downloading pieces from them.

    Sent Message:
        interested: <len=0001><id=2>

    Args:
        writer: Writer stream object used to send data to the peer
    """
    length = 1
    msg_id = 2
    interested_msg = struct.pack(">IB", length, msg_id)

    writer.write(interested_msg)
    print("[INTERESTED : INFO] Sent interested message to peer -> Message ID: 2")
    await writer.drain()

async def wait_for_unchoke(reader):
    """
    After sending the intereseted message the peer can either
        "Choke Us" - not allow us to download pieces from them
        "Unchoke Us" - allow us to donload pieces from them
    They also send us a bitfield message which is just a huge byte string in which represents the pieces that they have

    Received Messages:
        Choke: <len=0001><id=0>
        Unchoke: <len=0001><id=1>
        Bitfield: <len=N><id=5><bitfield>
        Have: <len=0005><id=4><piece_index (4bytes)>

    Args:
        reader: Reader stream object to send data to the peer
    """
    try:
        bitfield = []
        unchoked = False
        got_bitfield = False
        async with asyncio.timeout(15):
            while True:
                msg_len_prefix = await reader.readexactly(4)
                msg_len = int.from_bytes(msg_len_prefix, "big")

                if msg_len == 0:
                    continue

                message = await reader.readexactly(msg_len)
                msg_id = message[0]

                if msg_id == 5:
                    bitfield_bytes = message[1:]
                    # GPT generated idk how to play with bits
                    for byte in bitfield_bytes:
                        for i in range(8):
                            bitfield.append((byte >> (7 - i)) & 1)
                    got_bitfield = True
                    print("[BITFIELD : INFO] Successfully received and parsed bitfield from peer -> Message ID: 5")
                elif msg_id == 0:
                    print("[UNCHOKE : INFO] Peer does not want to unchoke us -> Message ID: 0")
                elif msg_id == 1:
                    unchoked = True
                    print("[UNCHOKE : INFO] Received unchoke message from peer -> Message ID: 1")
                elif msg_id == 4:
                    if msg_len != 5:
                        print(f"[HAVE : ERROR] Received malformed HAVE message from peer")
                        continue
                    piece_idx = int.from_bytes(message[1:], "big")
                    if piece_idx >= len(bitfield):
                        bitfield.extend([0] * (piece_idx + 1 - len(bitfield)))

                    bitfield[piece_idx] = 1
                    print(f"[HAVE : INFO] Peer announced it has piece {piece_idx}")
                else:
                    print(f"[UNCHOKE : INFO] Ignoring message from peer -> Message ID: {msg_id}")

                if unchoked and got_bitfield:
                    return unchoked, bitfield

    except asyncio.TimeoutError:
        print("[UNCHOKE : TIMEOUT] Peer did not respond with unchoke or bitfield in time")
    except asyncio.IncompleteReadError:
        print("[UNCHOKE : ERROR] Peer closed connection unexpectedly.")
    except Exception as e:
        print("[UNCHOKE : ERROR] Some error occured during waiting for unchoke")
        print(traceback.format_exc())

    return False, []


async def request_piece(writer, piece_index: int, piece_length: int, metadata: dict, block_size: int = 2**14):
    """
    In bittorrent protocol, the file is broken down into small pieces of size depending on the way the .torrent file defines
    it. Each piece is then broeken down into smaller blocks which are 16KB in size usually. This function sequentially sends
    the request message to the peer for all the blocks in a piece

    Sent Message:
        request_piece: <len=13><msg_id=6><piece_index><offset><block_size>

    Args:
        writer: Writer stream object to write to the connected peer
        piece_index: The index of the piece of that we want the peer to send
        piece_length: The length of each piece defined by the .torrent file
        metadata: The metadata parsed from the .torrent file, we want the total file length from this
        block_size: The size of the smaller blocks that we will be requestiong from the peer defaults to 2**14 (16KB)
    """
    try:
        msg_len = 13
        msg_id = 6

        if piece_index == metadata.get("piece count") - 1:
            actual_length = (metadata.get("total length") - (piece_index * piece_length))
        else:
            actual_length = piece_length

        for offset in range(0, actual_length, block_size):
            this_block_size = min(block_size, actual_length - offset)
            message = struct.pack(">IBIII", msg_len, msg_id, piece_index, offset, this_block_size)
            writer.write(message)
            await writer.drain()
            print(f"[REQUEST : INFO] Requested block -> Piece: {piece_index} | Offset: {offset} | Length: {this_block_size}")
    except Exception as e:
        print("[REQUEST : ERROR] Failed to send piece request to peer")
        print(traceback.format_exc())

async def receive_piece(reader, piece_index: int, piece_length: int, metadata: dict, block_size: int = 2**14):
    """
    This function receives all the blocks that make up a specific piece from the peer. It continues reading from the peer
    until a full piece is received

    Received Message:
        piece: <len=9+X><msg_id=7><index><begin><block> (X is the length of the block)

    Args:
        reader: Reader stream object to receive messages from the peer
        piece_index: The index of the piece of that we want the peer to send
        piece_length: The length of each piece defined by the .torrent file
        metadata: The metadata parsed from the .torrent file, we want the total file length from this
        block_size: The size of the smaller blocks that we will be requestiong from the peer defaults to 2**14 (16KB)
    """
    # TODO : Need to figure out a failsafe so that if the peer does break connection in b/w this function does not loop infinitely
    try:
        received_blocks = {}

        if piece_index == metadata.get("piece count") - 1:
            actual_length = (metadata.get("total length") - (piece_index * piece_length))
        else:
            actual_length = piece_length

        while (sum(len(block) for block in received_blocks.values()) < actual_length):
            msg_len_prefix =  await asyncio.wait_for(reader.readexactly(4), timeout=10)
            msg_len = int.from_bytes(msg_len_prefix, "big")

            if msg_len == 0:
                continue

            message = await reader.readexactly(msg_len)
            msg_id = message[0]

            if msg_id == 7:
                idx = int.from_bytes(message[1:5], "big")
                begin = int.from_bytes(message[5:9])
                block_data = message[9:]

                if idx != piece_index:
                    print(f"[REQUEST : WARN] Got back unexpected piece -> Requested (Piece {piece_index}) got (Piece {idx})")
                    continue

                received_blocks[begin] = block_data
                print(f"[RECEIVE : INFO] Got block at offset {begin} | Size {len(block_data)}")

            else:
                print(f"[REQUEST : INFO] Ignoring message from peer -> Message ID: {msg_id}")

        full_piece = b''.join([received_blocks[offset] for offset in sorted(received_blocks)])
        return full_piece
    except asyncio.TimeoutError:
        print(f"[RECEIVE : TIMEOUT] No response from peer for 10s")
        return b''
    except Exception as e:
        print(f"[RECIEVE : ERROR] Failed to receive complete piece -> Piece Index: {piece_index}")
        print(traceback.format_exc())
        return b''

def verify_piece_hash(recv_piece_data, piece_hash):
    """
    Each piece downloaded has a SHA1 hash in the parsed .torrent file, we check the downloaded piece with the SHA1 Hash of
    that piece to check if the piece is correct before sending it for writing

    Args:
        recv_piece_data: The piece data received from the peer
        piece_hash: The SHA1 piece hash of the piece
    """
    return hashlib.sha1(recv_piece_data).digest() == piece_hash

async def download_piece(ip, port, info_hash, peer_id, piece_index, piece_length, piece_hash, metadata):
    """
    This function is what brings all the parts of a requesting a piece from a peer together, its the sole function
    which is exposed to other files and main.py calls this function in order to download a piece

    Args:
        ip: IP of the peer you want to download from
        port: Port that the peer allowed us to communicate on
        info_hash: The SHA1 hash of the entire metadata
        peer_id: Our generated peer_id
        piece_index: The piece index that we want to download
        piece_length: The length of a singular piece specified by the .torrent file
        piece_hash: The SHA1 hash of the piece that we are downloading
        metadat: Parsed .torrent file in the form of a dict
    """
    reader, writer = None, None
    try:
        reader, writer = await (connect(ip, port))

        success = await handshake(reader, writer, info_hash, peer_id)
        if not success:
            print(f"[HANDSHAKE : FAILED] Could not complete handshake with {ip}:{port} successfully")
            return None
        else:
            print(f"[HANDSHAKE : DONE] Completed handshake with {ip}:{port} successfully")

        await send_interested(writer)

        unchoked, bitfield = await (wait_for_unchoke(reader))
        if not unchoked:
            return None

        if piece_index >= len(bitfield) or bitfield[piece_index] == 0:
            print(f"[BITFIELD : INFO] {ip}:{port} does not have the piece with index {piece_index}")
            return None

        await request_piece(writer, piece_index, piece_length, metadata)

        recv_piece_data = await receive_piece(reader, piece_index, piece_length, metadata)
        if recv_piece_data == b'':
            print(f"[RECEIVE : INFO] Did not receive Piece Index: {piece_index} from Peer: {ip}:{port}")
            return None

        if verify_piece_hash(recv_piece_data, piece_hash):
            print(f"[VERIFY : SUCCESS] Piece received from {ip}:{port} passed SHA1 verification")
            return recv_piece_data
        else:
            print(f"[VERIFY : FAIL] Piece received from {ip}:{port} did not pass SHA1 verification")
            return None
    except OSError as e:
        if hasattr(e, 'winerror') and e.winerror == 121:
            print(f"[SOCKET : TIMEOUT] WinError 121: Peer {ip}:{port} timed out or disconnected")
        else:
            print("[SOCKET : ERROR] Unknown OSError occurred")
            print(e)
    except Exception as e:
        print("Error in download_piece")
        print(e)
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()
