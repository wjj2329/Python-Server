#!/usr/bin/env python

import sys
import argparse
import select
import logging
import errno
import socket
import traceback
from StringIO import StringIO
import os
import time

class Main:
    """ Parse command line options and run the server """
    def __init__(self):
        self.parse_arguments()

    def parse_arguments(self):
        """ parse arguments -p & -d """
        parser = argparse.ArgumentParser()
        parser.add_argument("-p", "--port", type=int, action="store", help="port the server will bind to", default=8080)
        parser.add_argument("-d", "--debug", help="print out debug info", action="store_true")
        self.args = parser.parse_args()
        if self.args.debug:
            logging.basicConfig(level=logging.DEBUG)
        logging.debug("Debugging is on")

    def run(self):
        server = WebServer(self.args.port)
        s = server.serve()
        logging.debug("The server has finished running")

class WebServer:
    def __init__(self, port):
        self.port = port
        self.parseConfig()
        self.host = "" # TODO: add checking for different hosts
        self.open_socket()
        self.clients = {}
        self.size = 1024
        self.times = {} # {file-descriptor : time-last-active, ...}
        logging.debug("The server has been initialized")
        self.cache={}

    def open_socket(self):
        """ Set up the socket for incoming clients """
        logging.debug("In the open_socket function")
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR,1)
            try:
                self.server.bind((self.host, self.port))
            except:
                print "Port %s is unavailable.  Exiting." % self.port
                if self.server:
                    self.server.close()
                sys.exit()
            self.server.listen(5)
            self.server.setblocking(0)
        except socket.error, (value, message):
            if self.server:
                self.server.close()
            #print "Could not open socket: " + message
            sys.exit()

    def serve(self):
        """use poll to handle each incoming client"""
        self.poller=select.epoll()
        self.pollmask=select.EPOLLIN| select.EPOLLHUP| select.EPOLLERR
        self.poller.register(self.server, self.pollmask)
        logging.debug("The epoller is initialized, server about to begin")
        while True:
            # TODO: maybe fix this times thing
            for fd, actTime in self.times.items():
                #print fd, actTime
                if time.time() - actTime > self.timeout:
                    if fd in self.clients:
                        self.handleClient(fd)
                if time.time() - actTime > self.timeout:
                    logging.debug("Killing fd %s after %s seconds" % (fd, time.time() - actTime))
                    self.poller.unregister(fd)
                    if fd in self.clients:
                        self.clients[fd].close()
                        del self.clients[fd]
                    del self.times[fd]

            #poll sockets
            try:
                fds=self.poller.poll(timeout=self.timeout) # TODO: Should this be the config['parameter']['timeout'] value?
            except:
                logging.debug("run(): something bad happened")
                return
            for(fd, event) in fds:
                #handle errors
                if event & (select.POLLHUP|select.POLLERR):
                    self.handleError(fd)
                    continue
                #handle the server socket
                if fd == self.server.fileno():
                    self.handleServer()
                    continue
                #handle client socket
                result=self.handleClient(fd)
        return "Hey"

    def handleError(self, fd):
        self.poller.unregister(fd)
        logging.debug("***Error with fd %s***" % fd)
        if fd == self.server.fileno():
            #recreate server socket
            self.server.close()
            self.open.socket()
            self.poller.register(self.server, self.pollmask)
        else:
            #close the socket
            #print "Closing socket %s" % fd
            self.clients[fd].close()
            del self.clients[fd]

    def handleServer(self):
        #accept as many clients as possible
        while True:
            try:
                (client, address)=self.server.accept()
                #logging.debug(client.getsockname())#  as far as what to use for the key for the dictionary I thought the socket would be appropriate
            except socket.error, (value, message):
                #if socket blocks because no clients are available
                #then return
                if value==errno.EAGAIN or errno.EWOULDBLOCK:
                    return
                print traceback.format_exc()
                sys.exit()
            #set client socket to be non blocking
            client.setblocking(0)
            #if client.fileno() in self.clients:
                #print ("\n\n%s already in clients!\n\n" % client.fileno()) * 50
            self.clients[client.fileno()]=client
            self.poller.register(client.fileno(), self.pollmask)
            self.times[client.fileno()] = time.time()

    def handleClient(self, fd):
        #logging.debug("Handling client with fd: " + str(fd))
        try:
            data=self.clients[fd].recv(self.size)
        except socket.error, (value, message):
            # if no data is available, move on to another client
            if value==errno.EAGAIN or errno.EWOULDBLOCK:
                return
            print traceback.format_exc()
            sys.exit()
        #logging.debug("%s started %s seconds ago" % (fd, time.time() - self.times[fd]))
        try:
            if data:
                self.times[fd] = time.time()
                logging.debug("\nReceived request:\n" + str(data))
                if self.isfullrequest(data, fd): 
                #if True:
                    data = self.handleRequest(self.cache[fd])
                    #data = self.handleRequest(data)
                    bytesSent = 0
                    totBytes = len(data)
                    #print "Trying to send %s bytes to fd %s" % (totBytes, fd)
                    #print "self.clients[fd] is %s" % self.clients[fd]
                    while bytesSent < totBytes:
                        try:
                            bytesSent += self.clients[fd].send(data[bytesSent:])
                        except socket.error, (value, message):
                            if value == errno.EAGAIN or errno.EWOULDBLOCK:
                                continue
                            print traceback.format_exc()
                            sys.exit()
                    #print "Sent %s bytes" % bytesSent
                    del self.cache[fd]
        except socket.error, (value, message):
            #print "Didn't send everything the right way.. value: %s" % value
            if value == errno.EAGAIN or errno.EWOULDBLOCK:
                return
            print traceback.format_exc()
            sys.exit()

    def parseConfig(self):
        self.config = {'host': {}, 'media': {}, 'parameter': {} }
        with open("web.conf","r") as confFile:
            for line in confFile:
                line = line.strip().split()
                if len(line) < 3:
                    continue
                self.config[line[0]][line[1]] = line[2]
        self.timeout = float(self.config['parameter']['timeout'])
        logging.debug("Config parsed:")
        logging.debug(self.config)
        logging.debug("the timeout is "+str(self.timeout))

    def isfullrequest(self, data, fd):
        #logging.debug("this is the end of the request I hope"+req.endswith())
        req = StringIO(data).read()
        if fd not in self.cache:
            self.cache[fd]=req
        else:
            #print self.cache
            logging.debug("i append to the cache some more it looks like this "+self.cache[fd])
            self.cache[fd] += req
        logging.debug("does it look likes this "+"\r\n\r\n")
        if self.cache[fd].endswith("\r\n\r\n"):
            logging.debug("i got the end of the response")
            return True
        return False
   	
    def handleRequest(self, request):
        # Parse the request and prepare and return a response
        lb = "\r\n" # line break
        req = StringIO(request)
        reqType = req.readline().rstrip().split(" ")
        headers = self.parseHeaders(request)
        if reqType == ['GET']:
            reqType = ['GET','/','HTTP/1.1']
        if len(reqType) != 3:
            # 400 Bad Request
            logging.debug(reqType)
            respStr = "<head><title>No good</title></head><body>Bad request.</body>"
            return "HTTP/1.1 400 Bad Request\r\nContent-Type: text/html%s\r\n\r\n%s\r\n\r\n" % (self.getHeaderString(len(respStr)), respStr)
        if reqType[0].upper() not in ["HEAD","GET"] or reqType[2].upper() != "HTTP/1.1":
            # 501 Not Implemented
            respStr = "<head><title>No good</title></head><body>Not implemented.</body>"
            return "HTTP/1.1 501 Not Implemented\r\nContent-Type: text/html%s\r\n\r\n%s\r\n\r\n" % (self.getHeaderString(len(respStr)), respStr)
        if reqType[1] == "/":
            reqType[1] = "index.html"
        try:
            # Open the file
            host = "default"
            if "Host" in headers:
                if headers["Host"] in self.config["host"]:
                    host = headers["Host"]
            reqFile = self.config["host"][host] + "/" + reqType[1]
            logging.debug(reqFile)
            ext = reqFile.split(".")[-1]
            f = open(reqFile,"rb")
            pass
        except IOError, ioe:
            if ioe.errno == 13:
                # 403 Forbidden response
                respStr = "<head><title>No good</title></head><body>Forbidden.</body>"
                return "HTTP/1.1 403 Forbidden\r\nContent-Type: text/html%s\r\n\r\n%s\r\n\r\n" % (self.getHeaderString(len(respStr)), respStr)
            elif ioe.errno == 2:
                # 404 Not Found
                respStr = "<head><title>No good</title></head><body>Not found.</body>"
                return "HTTP/1.1 404 Not Found\r\nContent-Type: text/html%s\r\n\r\n%s\r\n\r\n" % (self.getHeaderString(len(respStr)), respStr)
        except:
            raise
            # 500 Internal Server Error
            respStr = "<head><title>No good</title></head><body>Internal Server Error.</body>"
            return "HTTP/1.1 500 Internal Server Error\r\nContent-Type: text/html%s\r\n\r\n%s\r\n\r\n" % (self.getHeaderString(len(respStr)), respStr)
        # 206 Partial Content
        if "Range" in headers:
            try:
                rFrom, rTo = [int(x) for x in headers["Range"].replace("bytes=","").split("-")]
                return "HTTP/1.1 206 Partial Content\r\nContent-Type: " + self.config["media"][ext] + \
                        self.getHeaderString(rTo-rFrom+1, os.path.getmtime(reqFile)) + \
                        "\r\nContent-Range: bytes %s-%s/%s" % (rFrom, rTo, os.path.getsize(reqFile)) + \
                        "\r\n\r\n" + "".join([line for line in f])[rFrom: rTo+1]
            except:
                pass
        # 200 OK
        if reqType[0].upper() == "GET":
            return "HTTP/1.1 200 OK\r\nContent-Type: " + self.config["media"][ext] + \
                    self.getHeaderString(os.path.getsize(reqFile), os.path.getmtime(reqFile)) + \
                    "\r\n\r\n" + "".join([line for line in f])
        elif reqType[0].upper() == "HEAD":
            return "HTTP/1.1 200 OK\r\nContent-Type: " + self.config["media"][ext] + \
                    self.getHeaderString(os.path.getsize(reqFile), os.path.getmtime(reqFile)) + \
                    "\r\n\r\n"

    def parseHeaders(self, request):
        headers = {}
        req = StringIO(request)
        toss = req.readline()
        for line in req:
            line = line.strip().split(": ")
            try:
                headers[line[0]] = line[1]
            except:
                continue
        return headers

    def getHeaderString(self, contLen=0, lastMod=None):
        header = "\r\nContent-Length: " + str(contLen) + \
                "\r\nDate: " + time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime()) + \
                "\r\nServer: web"
        if lastMod:
            header += "\r\nLast-Modified: " + time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(lastMod))
        return header

    def run(self):
        pass

if __name__ == "__main__":
    m = Main()
    try:
        m.run()
    except KeyboardInterrupt:
        pass
