import os
import random
from abc import abstractproperty
from abc import abstractmethod

from ect import crypto
from ect.exceptions import BeingAttacked
from ect.exceptions import NoAuthentication
from ect.message import Client
from ect.message import Server
from ect.crypto import derive_new_key


class ChatClientBase(object):
   
    _g = 2
    _p = 282755483533707287054752184321121345766861480697448703443857012153264407439766013042402571
    _shared_key = None

    @abstractproperty
    def Ks(self):
        """Session key"""
        raise NotImplementedError

    # GUI should call this fucntion to set the shared key set by TA
    def set_shared_key(self, key=None):
        self._shared_key = derive_new_key(key)
    
    @property
    def authenticated(self):
        """Determine if we are authenticated by checking for a session key"""
        return self.Ks is not None

    @abstractmethod
    def send(self, message):
        """Send a message to the remote"""
        raise NotImplementedError

    @abstractmethod
    def recv(self):
        """This method should be invoked as a thread and be continually
        listening for and receiving messages
        """
        raise NotImplementedError

    def extract_auth_msg_parts(self, m):
        ident, nonce, public_key = m[:crypto.BLOCK_SIZE], \
                                   m[crypto.BLOCK_SIZE:crypto.BLOCK_SIZE*2], \
                                   m[crypto.BLOCK_SIZE*2:]
        return ident, nonce, public_key 


class ChatClientClient(ChatClientBase):
    """Alice"""
    def __init__(self, remote_ip, remote_port, local_ip="0.0.0.0"):
        local_port = remote_port + 20
        self.client = Client(remote_ip, remote_port)
        print("{}.client connected on {}:{}".format(self.__class__.__name__,
            remote_ip, remote_port))
        self.server = Server(local_ip, local_port)
        print("{}.server connected on {}:{}".format(
            self.__class__.__name__, local_ip, local_port))
        self._mutau_state = self.MUTUAL_AUTH_STATES[-1]
        self._session_key = None
        self._shared_key = None
        self._secret_value = random.getrandbits(crypto.BLOCK_SIZE)
        while pow(self._g, self._secret_value) < self._p:
            print "redoing g^a"
            self._secret_value = random.getrandbits(crypto.BLOCK_SIZE)

    MUTUAL_AUTH_STATES = {
        -1: None,
        0: "NOTIFY_REMOTE",
        1: "VERIFY_REMOTE",
        2: "IDENTIFY_SELF_TO_REMOTE"
    }


    @property
    def Ks(self):
        return self._session_key

    def mutauth_step(self, reset=False):
        """This method steps through mutual authentication 
            and key exchange using Diffie-Helman

        Each call to this method will perform one step out of the
         total steps necessary for authentication

        :param bool reset: If this is set, we reset back to step -1
        """
        if reset or self._shared_key is None:
            self._mutau_state = self.MUTUAL_AUTH_STATES[-1]
            # TODO: GUI should show something when shared key is not set
            return

        if self._mutau_state == self.MUTUAL_AUTH_STATES[-1]:
            # Send our public key (Ra)
            self._Ra = os.urandom(crypto.BLOCK_SIZE)
            self.client.send(self._Ra)
            
            self._mutau_state = self.MUTUAL_AUTH_STATES[0]
            print "step1 done"
        elif self._mutau_state == self.MUTUAL_AUTH_STATES[0]:
            # Get response: RB, E("Bob", RA, gb mod p, KAB)
            resp = self.server.recv()
            self._rb = resp[:crypto.BLOCK_SIZE]
            ct = resp[crypto.BLOCK_SIZE:]
            pt = crypto.decrypt(self._shared_key, ct)
            self._server_ident, ra, gb_mod_p = self.extract_auth_msg_parts(pt)

            # TODO: probably GUI should call this function with reset=True
            # and display being attacked
            if ra != self._Ra:
                raise BeingAttacked("Trudy is attacking")

            self._session_key = pow(long(gb_mod_p), self._secret_value, self._p)
            
            self._mutau_state = self.MUTUAL_AUTH_STATES[1]
            print "step2 done"
        elif self._mutau_state == self.MUTUAL_AUTH_STATES[1]:
            # Send E("Alice", RB, ga mod p, KAB)

            # Client identifier can be anything other the the server's ident
            identifier = os.urandom(crypto.BLOCK_SIZE)
            while identifier == self._server_ident:
                identifier = os.urandom(crypto.BLOCK_SIZE)
            
            ga_mod_p = pow(self._g, self._secret_value, self._p)
            pt = identifier + self._rb + str(ga_mod_p)
            ct = crypto.encrypt(self._shared_key, pt) 
            self.client.send(ct)
            
            self._mutau_state = self.MUTUAL_AUTH_STATES[2]
            print "step3 done"
            self._session_key = crypto.derive_new_key(str(self._session_key))
        elif self._mutau_state == self.MUTUAL_AUTH_STATES[2]:

            raise StopIteration("Authentication completed successfully.")


    def send(self, message):
        if self.authenticated == True:
            ct = crypto.encrypt(self._session_key, message)
            self.client.send(ct)
        else:
            raise NoAuthentication("No Authentication Established")

    def recv(self, nb=False):
        if self.authenticated == True:
            ct = self.server.recv() if not nb else self.server.nb_recv()
            if ct is None:
                return None
            pt = crypto.decrypt(self._session_key, ct)
            return pt
        else:
            raise NoAuthentication("No Authentication Established")

class ChatClientServer(ChatClientBase):
    """Bob"""
    
    # Can be anything
    _identifier = "BOB12345678901234567890123456789"

    MUTUAL_AUTH_STATES = {
        -1: None,
        0: "WAIT",
        1: "IDENTIFY_SELF_TO_REMOTE",
        2: "VERIFY_REMOTE"
    }


    @property
    def Ks(self):
        return self._session_key

    def __init__(self, local_ip="0.0.0.0", local_port=8051):
        # Start server first, then client (opposite order from ChatClientClient
        self.server = Server(local_ip, local_port)
        print("{}.server connected on {}:{}".format(
            self.__class__.__name__, local_ip, local_port))
        remote_ip, _ = self.server.client_address
        remote_port = local_port + 20
        self.client = Client(remote_ip, remote_port)
        print("{}.client connected on {}:{}".format(self.__class__.__name__,
            remote_ip, remote_port))
        self._mutau_state = self.MUTUAL_AUTH_STATES[-1]
        self._secret_value = random.getrandbits(crypto.BLOCK_SIZE)
        while pow(self._g, self._secret_value) < self._p:
            print "redoing g^a"
            self._secret_value = random.getrandbits(crypto.BLOCK_SIZE)

    def mutauth_step(self, reset=False):
        if reset or self._shared_key is None:
            # GUI should show something when shared key is None
            self._mutau_state = self.MUTUAL_AUTH_STATES[-1]
            return

        if self._mutau_state == self.MUTUAL_AUTH_STATES[-1]:
            # Receive client's nonce
            self._Ra = self.server.recv()
           
            self._mutau_state = self.MUTUAL_AUTH_STATES[0]
            print "step1 done"
        elif self._mutau_state == self.MUTUAL_AUTH_STATES[0]:
            # Send response: RB, E("Bob", RA, gb mod p, KAB)
            self._Rb = os.urandom(crypto.BLOCK_SIZE)
            gb_mod_p = pow(self._g, self._secret_value, self._p)
            pt = self._identifier + self._Ra + str(gb_mod_p)
            ct = crypto.encrypt(self._shared_key, pt)
            msg = self._Rb + ct
            self.client.send(msg)
           
            self._mutau_state = self.MUTUAL_AUTH_STATES[1]
            print "step2 done"
        elif self._mutau_state == self.MUTUAL_AUTH_STATES[1]:
            # Receive E("Alice", RB, ga mod p, KAB)
            ct = self.server.recv()
            pt = crypto.decrypt(self._shared_key, ct)
            identifier, rb, ga_mod_p = self.extract_auth_msg_parts(pt)
            
            # TODO: probably GUI should call this function with reset=True
            # and display being attacked
            if rb != self._Rb:
                raise BeingAttacked("Trudy is attacking")
            # TODO: probably GUI should calls this function with reset=True 
            # and display being attacked
            if identifier == self._identifier:
                raise BeingAttacked("Trudy is doing replay attack")

            self._session_key = pow(long(ga_mod_p), self._secret_value, self._p)
            
            self._mutau_state = self.MUTUAL_AUTH_STATES[2]
            print "step3 done"
            self._session_key = crypto.derive_new_key(str(self._session_key))
        elif self._mutau_state == self.MUTUAL_AUTH_STATES[2]:
            raise StopIteration("Authentication completed successfully.")

    def send(self, message):
        if self.authenticated == True:
            ct = crypto.encrypt(self._session_key, message)
            self.client.send(ct)
        else:
            raise NoAuthentication("No Authentication Established")

    def recv(self, nb=False):
        if self.authenticated == True:
            ct = self.server.recv() if not nb else self.server.nb_recv()
            if ct is None:
                return None
            pt = crypto.decrypt(self._session_key, ct)
            return pt
        else:
            raise NoAuthentication("No Authentication Established")
