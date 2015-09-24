#!/usr/bin/env python

import multiprocessing
from flask import Flask, render_template, request, redirect, url_for, flash
import time
import zmq
import socket
import os

CLOUD_XFD_DATA = "/home/pi/extremefeedbacklamp/cloud-xfd.data"
NETWORK_INTERFACE = "/home/pi/extremefeedbacklamp/net-iface.data"

def get_iface():
    """Get the network interface configured in the data file"""
    if not os.path.isfile(NETWORK_INTERFACE):
        with open(NETWORK_INTERFACE, "w") as f:
            # Default eth0
            f.write("eth0")
    with open(NETWORK_INTERFACE, "r") as f:
        return f.read().rstrip()

def get_url():
    """Get the url stored in the data file"""
    if not os.path.isfile(CLOUD_XFD_DATA):
        with open(CLOUD_XFD_DATA, "w") as f:
            f.write("")

    with open(CLOUD_XFD_DATA, "r") as f:
        return f.read().rstrip()


def put_url(address):
    """Update the url stored in the data file"""
    with open(CLOUD_XFD_DATA, "w") as f:
        f.write(address)


def http_worker(lock):
    """The Flask application"""
    app = Flask("cloud_xfd")

    # noinspection PyUnusedLocal
    @app.route("/")
    def index():
        with lock:
            url = get_url()
        return render_template("index.html", url=url)

    # noinspection PyUnusedLocal
    @app.route("/update", methods=["POST"])
    def update():
        address = request.form["url"]
        with lock:
            put_url(address)

        flash("The URL has been successfully updated")
        return redirect(url_for('index'))

    app.template_folder = "/home/pi/extremefeedbacklamp/templates"
    app.secret_key = "notreallyasecret"
    app.run('0.0.0.0')


def clean_url(address):
    """Remove unwanted data and provide a default value (127.0.0.1)"""
    if address == "":
        return '127.0.0.1'
    address = address.replace("http://", "")
    address = address.replace("https://", "")
    address = address.split(":")[0]
    return address


def zeromq_worker(lock):
    """The ZeroMQ poller"""
    with lock:
        address = clean_url(get_url())

    context = zmq.Context()
    zmq_socket = context.socket(zmq.REQ)
    zmq_socket.connect('tcp://' + address + ':61616')
    poller = zmq.Poller()
    poller.register(zmq_socket, zmq.POLLIN)

    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    interface = "/sys/class/net/" + get_iface() + "/address"
    if os.path.isfile(interface):
        with open(interface, "r") as f:
            mac_address = f.read()
    else:
        mac_address = "test"

    while True:
        zmq_socket.send(mac_address, zmq.NOBLOCK)
        while True:
            with lock:
                new_address = clean_url(get_url())

            if new_address != address:
                url = new_address
                zmq_socket.close()
                zmq_socket = context.socket(zmq.REQ)
                zmq_socket.connect('tcp://' + url + ':61616')
                poller = zmq.Poller()
                poller.register(zmq_socket, zmq.POLLIN)
                zmq_socket.send(mac_address, zmq.NOBLOCK)

            messages = dict(poller.poll(1000))
            if messages:
                break
            else:
                time.sleep(1)

        message = zmq_socket.recv()

        if message:
            for part in message.split("\a"):
                udp_socket.sendto(part, ("0.0.0.0", 39418))

        time.sleep(1)


def cloud_xfd():
    """The main function.
    Please note that we are using processes instead of functions
    because Flask prefers to be running in the main thread"""
    lock = multiprocessing.Lock()

    http_process = multiprocessing.Process(target=http_worker, args=(lock,))
    http_process.daemon = True
    http_process.start()
    with lock:
        print "http process started"

    zmq_process = multiprocessing.Process(target=zeromq_worker, args=(lock,))
    zmq_process.daemon = True
    zmq_process.start()
    with lock:
        print "zmq thread started"

    http_process.join()
    zmq_process.join()


if __name__ == "__main__":
    cloud_xfd()
