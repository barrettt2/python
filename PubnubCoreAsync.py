## www.pubnub.com - PubNub Real-time push service in the cloud. 
# coding=utf8

## PubNub Real-time Push APIs and Notifications Framework
## Copyright (c) 2010 Stephen Blum
## http://www.pubnub.com/

## -----------------------------------
## PubNub 3.1 Real-time Push Cloud API
## -----------------------------------
import sys
import json
import time
import hashlib
import urllib2
import uuid
try:
    from hashlib import sha256
    digestmod = sha256
except ImportError:
    import Crypto.Hash.SHA256 as digestmod
    sha256 = digestmod.new
import hmac
from twisted.internet import reactor
from twisted.internet.defer import Deferred
from twisted.internet.protocol import Protocol
from twisted.web.client import Agent
from twisted.web.client import HTTPConnectionPool
from twisted.web.http_headers import Headers
from PubnubCrypto import PubnubCrypto
import gzip
import zlib

pnconn_pool = HTTPConnectionPool(reactor)
pnconn_pool.maxPersistentPerHost    = 100
pnconn_pool.cachedConnectionTimeout = 310

class PubnubCoreAsync(object):

    def start(self): pass 
    def stop(self):  pass
    def timeout( self, delay, callback ):
        pass

    def __init__(
        self,
        publish_key,
        subscribe_key,
        secret_key = False,
        cipher_key = False,
        ssl_on = False,
        origin = 'pubsub.pubnub.com',
        uuid = None
    ) :
        """
        #**
        #* Pubnub
        #*
        #* Init the Pubnub Client API
        #*
        #* @param string publish_key required key to send messages.
        #* @param string subscribe_key required key to receive messages.
        #* @param string secret_key required key to sign messages.
        #* @param boolean ssl required for 2048 bit encrypted messages.
        #* @param string origin PUBNUB Server Origin.
        #**

        ## Initiat Class
        pubnub = Pubnub( 'PUBLISH-KEY', 'SUBSCRIBE-KEY', 'SECRET-KEY', False )

        """
        self.origin        = origin
        self.publish_key   = publish_key
        self.subscribe_key = subscribe_key
        self.secret_key    = secret_key
        self.cipher_key    = cipher_key
        self.ssl           = ssl_on
        self.subscriptions = {}
        self.timetoken     = 0
        self.uuid          = uuid or str(self.uuid()) 
        self.headers       = {
            'V' : '3.1',
            'User-Agent' : 'Python-*',
            'Accept-Encoding' : 'gzip'
        }

        if self.ssl :
            self.origin = 'https://' + self.origin
        else :
            self.origin = 'http://'  + self.origin


    def publish( self, args ) :
        """
        #**
        #* Publish
        #*
        #* Send a message to a channel.
        #*
        #* @param array args with channel and message.
        #* @return array success information.
        #**

        ## Publish Example
        def publish_complete(info):
            print(info)

        pubnub.publish({
            'channel' : 'hello_world',
            'message' : {
                'some_text' : 'Hello my World'
            },
            'callback' : publish_complete
        })

        """
        ## Capture Callback
        if args.has_key('callback'): callback = args['callback']
        else: callback = lambda x : x

        ## Fail if bad input.
        if not (args['channel'] and args['message']):
            callback([ 0, 'Missing Channel or Message', 0 ])
            return False

        ## Capture User Input
        channel = str(args['channel'])
        message = args['message']

        if self.cipher_key :
            pc = PubnubCrypto()
            out = []
            if type( message ) == type(list()):
                for item in message:
                    encryptItem = pc.encrypt(self.cipher_key, item ).rstrip()
                    out.append(encryptItem)
                message = json.dumps(out)
            elif type( message ) == type(dict()):
                outdict = {}
                for k, item in message.iteritems():
                    encryptItem = pc.encrypt(self.cipher_key, item ).rstrip()
                    outdict[k] = encryptItem
                    out.append(outdict)
                message = json.dumps(out[0])
            else:
                message = json.dumps(pc.encrypt(self.cipher_key, message).replace('\n',''))
        else :
            message = json.dumps(args['message'])

        def publish_response(info):
            callback(info or [0, 'Disconnected', 0]);

        ## Sign Message
        if self.secret_key :
            hashObject = sha256()
            hashObject.update(self.secret_key)
            hashedSecret = hashObject.hexdigest()
            hash = hmac.HMAC(hashedSecret, '/'.join([
                    self.publish_key,
                    self.subscribe_key,
                    self.secret_key,
                    channel,
                    message
                ]), digestmod=digestmod)
            signature = hash.hexdigest()        
        else :
            signature = '0'

        ## Send Message
        return self._request({ "urlcomponents" : [
            'publish',
            self.publish_key,
            self.subscribe_key,
            signature,
            channel,
            '0',
            message
        ] }, publish_response )



    def subscribe( self, args ) :
        """
        #**
        #* Subscribe
        #*
        #* This is NON-BLOCKING.
        #* Listen for a message on a channel.
        #*
        #* @param array args with channel and message.
        #* @return false on fail, array on success.
        #**

        ## Subscribe Example
        def receive(message) :
            print(message)
            return True

        ## On Connect Callback
        def connected() :
            pubnub.publish({
                'channel' : 'hello_world',
                'message' : { 'some_var' : 'text' }
            })

        ## Subscribe
        pubnub.subscribe({
            'channel'  : 'hello_world',
            'connect'  : connected,
            'callback' : receive
        })

        """
        ## Fail if missing channel
        if not 'channel' in args :
            return 'Missing Channel.'

        ## Fail if missing callback
        if not 'callback' in args :
            return 'Missing Callback.'

        ## Capture User Input
        channel   = str(args['channel'])
        callback  = args['callback']
        connectcb = args['connect']

        if 'errorback' in args:
            errorback = args['errorback']
        else:
            errorback = lambda x: x

        ## New Channel?
        if not (channel in self.subscriptions) :
            self.subscriptions[channel] = {
                'first'     : False,
                'connected' : False,
            }

        ## Ensure Single Connection
        if self.subscriptions[channel]['connected'] :
            return "Already Connected"

        self.subscriptions[channel]['connected'] = 1
        ## SUBSCRIPTION RECURSION 
        def substabizel():
            ## STOP CONNECTION?
            if not self.subscriptions[channel]['connected']:
                return
          
            def sub_callback(response):
                print response
                response = json.loads(response)
                ## STOP CONNECTION?
                if not self.subscriptions[channel]['connected']:
                    return

                ## CONNECTED CALLBACK
                if not self.subscriptions[channel]['first'] :
                    self.subscriptions[channel]['first'] = True
                    connectcb()

                ## PROBLEM?
                if not response:
                    def time_callback(_time):
                        if not _time:
                            self.timeout( 1, substabizel )
                            return errorback("Lost Network Connection")
                        else:
                            self.timeout( 1, substabizel )

                    ## ENSURE CONNECTED (Call Time Function)
                    return self.time({ 'callback' : time_callback })

                self.timetoken = response[1]
                substabizel()

                pc = PubnubCrypto()
                out = []
                for message in response[0]:
                     if self.cipher_key :
                          if type( message ) == type(list()):
                              for item in message:
                                  encryptItem = pc.decrypt(self.cipher_key, item )
                                  out.append(encryptItem)
                              message = out
                          elif type( message ) == type(dict()):
                              outdict = {}
                              for k, item in message.iteritems():
                                  encryptItem = pc.decrypt(self.cipher_key, item )
                                  outdict[k] = encryptItem
                                  out.append(outdict)
                              message = out[0]
                          else:
                              message = pc.decrypt(self.cipher_key, message )
                     else :
                          message

                     callback(message)

            ## CONNECT TO PUBNUB SUBSCRIBE SERVERS
            try :
                self._request( { "urlcomponents" : [
                    'subscribe',
                    self.subscribe_key,
                    channel,
                    '0',
                    str(self.timetoken)
                ], "urlparams" : {"uuid":self.uuid} }, sub_callback )
            except :
                self.timeout( 1, substabizel )
                return

        ## BEGIN SUBSCRIPTION (LISTEN FOR MESSAGES)
        substabizel()


    def unsubscribe( self, args ):
        channel = str(args['channel'])
        if not (channel in self.subscriptions):
            return False

        ## DISCONNECT
        self.subscriptions[channel]['connected'] = 0
        self.subscriptions[channel]['timetoken'] = 0
        self.subscriptions[channel]['first']     = False


    def history( self, args ) :
        """
        #**
        #* History
        #*
        #* Load history from a channel.
        #*
        #* @param array args with 'channel' and 'limit'.
        #* @return mixed false on fail, array on success.
        #*

        ## History Example
        history = pubnub.history({
            'channel' : 'hello_world',
            'limit'   : 1
        })
        print(history)

        """
        ## Capture User Input
        limit   = args.has_key('limit') and int(args['limit']) or 10
        channel = str(args['channel'])

        ## Fail if bad input.
        if not channel :
            return 'Missing Channel'

        ## Get History
        pc = PubnubCrypto()
        return self._request( {"urlcomponents" : [
            'history',
            self.subscribe_key,
            channel,
            '0',
            str(limit)
        ]}, args['callback'] )

    def time( self, args ) :
        """
        #**
        #* Time
        #*
        #* Timestamp from PubNub Cloud.
        #*
        #* @return int timestamp.
        #*

        ## PubNub Server Time Example
        def time_complete(timestamp):
            print(timestamp)

        pubnub.time(time_complete)

        """
        def complete(response) :
            if not response: return 0
            args['callback'](response[0])

        self._request( { "urlcomponents" : [
            'time',
            '0'
        ]}, complete )

    def uuid(self) :
        """
        #**
        #* uuid
        #*
        #* Generate a UUID
        #*
        #* @return  UUID.
        #*

        ## PubNub UUID Example
        uuid = pubnub.uuid()
        print(uuid)
        """
        return uuid.uuid1()

    def getUrl(self,request):
        ## Build URL
        url = self.origin + '/' + "/".join([
            "".join([ ' ~`!@#$%^&*()+=[]\\{}|;\':",./<>?'.find(ch) > -1 and
                hex(ord(ch)).replace( '0x', '%' ).upper() or
                ch for ch in list(bit)
            ]) for bit in request["urlcomponents"]])
        if (request.has_key("urlparams")):
            url = url + '?' + "&".join([ x + "=" + y  for x,y in request["urlparams"].items()])
        return url

    def _request( self, request, callback, timeout=30 ) :
        pass
