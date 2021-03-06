import packet_transmission
import packet_retrieval
import packet_ping
import packet_processing
import sys
import socket
import re
import logging
import logging.handlers
import os
import json

import threading
from queue import Queue, PriorityQueue

from packets import Packet
from packets import FilePacket
from packets import json_to_packet

# Globals needing locks
Hub = [None, None]
Star_map = {}
End = [False]
History = []

# Global Queues
Trans_queue = PriorityQueue()
Recv_queue = Queue()

if __name__ == "__main__":
    name = sys.argv[1]
    l_addr = socket.gethostbyname(socket.gethostname())
    l_port = sys.argv[2]
    max_nodes = sys.argv[5]
    poc_addr = sys.argv[3]
    poc_port = sys.argv[4]

    # Initialize logger
    logger = logging.getLogger('node')
    logger.setLevel(logging.DEBUG)
    logging_filename = 'node-{:s}.log'.format(name)
    # create file handler which logs even debug messages
    # fh = logging.FileHandler('node-{:s}.log'.format(name))
    should_roll_over = os.path.isfile(logging_filename)
    fh = logging.handlers.RotatingFileHandler(logging_filename, mode='w', backupCount=0)
    if should_roll_over:  # log already exists, roll over!
        fh.doRollover()
    fh.setLevel(logging.DEBUG)
    # create console handler with a higher log level
    ch = logging.StreamHandler()
    ch.setLevel(logging.ERROR)
    # create formatter and add it to the handlers
    formatter = logging.Formatter('%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    # add the handlers to the logger
    logger.addHandler(fh)
    logger.addHandler(ch)

    # regex initialization for different send message matching
    string_pattern = re.compile("^send \".+\"$")
    file_pattern = re.compile("^send .+[.][a-z]+$")

    # initialize static variables (these never change)
    identity = name + ":" + l_addr + ":" + l_port
    n = max_nodes
    default_threshold = 4

    # create our initial node entry in the star map
    Star_map[(l_addr, int(l_port))] = [0, 0, 0, default_threshold]

    # create initial entry for POC if one exists:
    if poc_addr != '0':
        Star_map[(poc_addr, int(poc_port))] = [0, 0, 0, default_threshold]

    # initialize Hub to our node
    Hub[0], Hub[1] = l_addr, int(l_port)

    logger.info("Initialized node {:s} on {:s}:{:s}, max nodes {:s}, POC: {:s}:{:s}.".format(name, l_addr, l_port, max_nodes, poc_addr, poc_port))
    print("Initialized node {:s} on {:s}:{:s}, max nodes {:s}, POC: {:s}:{:s}.".format(name, l_addr, l_port, max_nodes, poc_addr, poc_port))

    # initialize locks
    map_lock = threading.Lock()
    hub_lock = threading.Lock()
    end_lock = threading.Lock()
    history_lock = threading.Lock()

    # create event for Ping Thread
    start_pings = threading.Event()

    # let's make some threads :)
    args1 = (Trans_queue, Star_map, map_lock, History, history_lock, End, end_lock)
    args2 = (Recv_queue, identity, End, end_lock)
    args3 = (Star_map, Hub, Trans_queue, History, history_lock, map_lock, hub_lock, identity, start_pings, End, end_lock, default_threshold)
    args4 = (Star_map, Hub, History, history_lock, Recv_queue, Trans_queue, map_lock, hub_lock, identity, n, start_pings, End, end_lock, default_threshold)
    trans_thread = threading.Thread(target=packet_transmission.core, name="trans", args=args1)
    recv_thread = threading.Thread(target=packet_retrieval.core, name="recv", args=args2)
    ping_thread = threading.Thread(target=packet_ping.core, name="ping", args=args3)
    proc_thread = threading.Thread(target=packet_processing.core, name="proc", args=args4)

    # start the threads :)
    try:
        trans_thread.start()
        recv_thread.start()
        ping_thread.start()
        proc_thread.start()
    except:
        # :(
        logger.error("Error occurred when starting threads")

    if poc_addr != '0':
        start_pings.set()

    # gonna put command line stuff here, feel free to move it
    while 1:
        user_input = input("\nStar-node command: ")

        # is send message?
        if string_pattern.match(user_input):
            # gets stuff between "'s -> send "<message>"
            message = user_input[user_input.find('"')+1:user_input.find('"', user_input.find('"')+1)]

            flag = False
            with hub_lock:
                curr_hub = Hub
                if curr_hub == [l_addr, int(l_port)]:
                    flag = True

            payload = json.dumps({
                "Message": message,
                "SourceAddr": l_addr,
                "SourcePort": l_port
            })

            if flag:
                with map_lock:
                    for node in Star_map:
                        if node != (l_addr, int(l_port)):
                            packet = Packet(payload, "MSG", l_addr, l_port, node[0], node[1])
                            Trans_queue.put((0, packet))
                            logger.info("Added packets to transmit message \"{:s}\" to send queue.".format(message))
            else:
                packet = Packet(payload, "MSG_HUB", l_addr, l_port, curr_hub[0], curr_hub[1])
                Trans_queue.put((0, packet))
                logger.info("Added packet with message to hub \"{:s}\" to send queue.".format(message))
        # is send file?
        elif file_pattern.match(user_input):
            # gets filename -> |s|e|n|d| |<filename>|
            filename = user_input[5:]

            flag = False
            with hub_lock:
                curr_hub = Hub
                if curr_hub == [l_addr, int(l_port)]:
                    flag = True

            if flag:
                with map_lock:
                    for node in Star_map:
                        if node != (l_addr, int(l_port)):
                            packet = FilePacket(filename, l_addr, l_port, node[0], node[1], True)
                            Trans_queue.put((0, packet))
                            logger.info("Added packets to transmit file \"{:s}\" to send queue.".format(filename))
            else:
                packet = FilePacket(filename, l_addr, l_port, curr_hub[0], curr_hub[1], False)
                Trans_queue.put((0, packet))
                logger.info("Added packet with file to hub \"{:s}\" to send queue.".format(filename))
        elif user_input == "show-status":
            print("--BEGIN STATUS--")
            with map_lock:
                for key, value in Star_map.items():
                    if value[2] < value[3]:
                        print("IDENTITY: {0}:{1} | RTT: {2} | RTT-SUM: {3} | TIMEOUT-COUNTER: {4}".format(key[0], key[1], value[1], value[0], value[2]))
                    else:
                        print("IDENTITY: {0}:{1} | TIMEOUT - DEAD".format(key[0], key[1]))
            with hub_lock:
                print("HUB: {0}:{1}".format(Hub[0], Hub[1]))
            print("--END STATUS--")
            logger.debug("Printed status.")
        elif user_input == "disconnect":
            logger.info("Node disconnected.")
            with end_lock:
                End[0] = True
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto("KILL".encode('utf-8'), (l_addr, int(l_port)))
            start_pings.set()
            recv_thread.join()
            ping_thread.join()
            trans_thread.join()
            proc_thread.join()
            break
        elif user_input == "show-log":
            print("--BEGIN LOG--")
            f = open(logging_filename, 'r')
            file_contents = f.read()
            print(file_contents.strip())
            f.close()
            print("--END LOG--")
            logger.debug("Printed log.")
        else:
            logger.error("Unknown command. Please use one of the following commands: send \"<message>\", "
                         "send <filename>, show-status, disconnect, or show-log.")
