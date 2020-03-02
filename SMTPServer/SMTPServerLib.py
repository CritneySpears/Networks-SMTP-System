import selectors
import queue
import traceback
import os.path
import SMTPServerEncryption
from threading import Thread
from os import path

class Module(Thread):
    def __init__(self, sock, addr):
        Thread.__init__(self)

        self._selector = selectors.DefaultSelector()
        self._sock = sock
        self._addr = addr
        self._state = "HELO"  # Start State
        self._commandlist = "COMMANDS: \n--HELO, \n--MAIL, \n--RCPT, \n--DATA, \n--RSET, \n--NOOP, \n--QUIT, \n--HELP"

        self._incoming_buffer = queue.Queue()
        self._outgoing_buffer = queue.Queue()

        self.encryption = SMTPServerEncryption.nws_encryption()

        events = selectors.EVENT_READ | selectors.EVENT_WRITE
        self._selector.register(self._sock, events, data=None)

        if not path.exists("MailBox"):
            os.mkdir("MailBox")

    def run(self):
        try:
            while True:
                events = self._selector.select(timeout=None)
                for key, mask in events:
                    try:
                        if mask & selectors.EVENT_READ:
                            self._read()
                        if mask & selectors.EVENT_WRITE and not self._outgoing_buffer.empty():
                            self._write()
                    except Exception:
                        print(
                            "main: error: exception for",
                            f"{self._addr}:\n{traceback.format_exc()}",
                        )
                        self._sock.close()
                if not self._selector.get_map():
                    break
        except KeyboardInterrupt:
            print("caught keyboard interrupt, exiting")
        finally:
            self._selector.close()

    def _read(self):
        try:
            data = self._sock.recv(4096)
        except BlockingIOError:
            print("blocked")
            # Resource temporarily unavailable (errno EWOULDBLOCK)
            pass
        else:
            if data:
                self._incoming_buffer.put(self.encryption.decrypt(data.decode()))
            else:
                raise RuntimeError("Peer closed.")

        self._process_response()

    def _write(self):
        try:
            message = self._outgoing_buffer.get_nowait()
        except:
            message = None

        if message:
            print("sending", repr(message), "to", self._addr)
            try:
                sent = self._sock.send(message)
            except BlockingIOError:
                # Resource temporarily unavailable (errno EWOULDBLOCK)
                pass

    def _create_message(self, content):
        encoded = self.encryption.encrypt(content)
        nwencoded = encoded.encode()
        self._outgoing_buffer.put(nwencoded)

    def _process_response(self):
        message = self._incoming_buffer.get()
        header_length = 4  # Specify command string length

        if len(message) >= header_length:
            self._module_processor(message[0:header_length], message[header_length:])  # Separate command and message

    def _mailbox_filename(self, addr):

        # Gets the address of the recipient and replaces "." with "_" to create a valid filename for the mailbox.

        filename = ""
        for i in addr:
            if i == ".":
                filename += "_"
            else:
                filename += i
        return filename

    def _get_address(self, message):

        # splits message to get address by checking for "<>"
        # returns INVALID if address not found

        _msg = str(message)
        _address_begin = _msg.find("<")
        _address_end = _msg.find(">")
        if (_address_begin >= 0) and \
            (_address_end >= 0) and \
                (_address_end > _address_begin):
            return message[_address_begin + 1:_address_end]
        else:
            return "INVALID"

    def _validate_address(self, message):

        # simple validation of the address.

        _msg = str(message)
        _address_begin = _msg.find("<")
        _address_end = _msg.find(">")
        _address_at = _msg.find("@")
        #
        #
        #
        return (_address_begin >= 0) and \
               (_address_at >= 0) and \
               (_address_end >= 0) and \
               (_address_begin < _address_at) and \
               (_address_at < _address_end)

    def _write_to_mailbox(self, message):
        mailbox = self._mailbox_filename(self._client_recipient_recipient)
        if message != ".":  # checks for CRLF, then writes messages to the mailbox
            f.write(message + "\n")
            f.close()  # Close the mailbox
        else:
            print("MESSAGE WRITTEN TO FILE")
            self._create_message("250 OK")
            self._state = "RSET"

# Commands Processed Here
    def _module_processor(self, command, message):

        command = command.upper()  # allow lower case commands

        if command == "NOOP":
            self._create_message("250 OK")
            print("Received a NOOP")

        elif command == "HELO":
            self._create_message("250 OK")
            print("Received a HELO")
            self._state = "MAIL"

        elif command == "MAIL":
            # Checks for a valid address, if so, stores sender address and moves to next state.
            if self._state == "MAIL":
                if self._validate_address(message):
                    self._client_sent_from = self._get_address(message)
                    self._create_message("250 OK")
                    print("MAIL FROM ", repr(self._client_sent_from))
                    self._state = "RCPT"
                else:
                    self._create_message("501: SYNTAX ERROR (BAD ADDRESS)")
                    print("ADDRESS INVALID")
            else:
                self._create_message("503: BAD SEQUENCE OF COMMANDS")
                print("INVALID COMMAND")

        elif command == "RCPT":
            # Similarly checks for valid address, and if so, stores the recipient address and moves to next state.
            if self._state == "RCPT":
                if self._validate_address(message):
                    self._client_recipient = self._get_address(message)
                    self._create_message("250 OK")
                    print("RCPT RECEIVED")
                    self._state = "DATA"
                else:
                    self._create_message("501: SYNTAX ERROR (BAD ADDRESS)")
                    print("ADDRESS INVALID")
            else:
                self._create_message("503: BAD SEQUENCE OF COMMANDS")
                print("INVALID COMMAND")

        elif command == "DATA":
            # Checks to see if there are valid addresses, then writes the message to mailbox and moves to next state.
            if self._state == "DATA":
                if self._client_sent_from != "" and self._client_recipient != "":
                    mailbox = self._mailbox_filename(self._client_recipient_recipient)
                    f = open("MailBox\\" + mailbox + ".txt", "a+")
                    f.write("FROM: " + self._client_sent_from + "\n")
                    f.write("TO: " + self._client_recipient + "\n")
                    f.close()  # Close the mailbox
                    self._create_message("354: START MAIL INPUT; END WITH ""'.'"" ON A NEW LINE")
                    transferring_message_content = true

                    if message != ".":  # checks for CRLF, then writes messages to the mailbox
                        f = open("MailBox\\" + mailbox + ".txt", "a+")
                        f.write(message + "\n")
                        f.close()  # Close the mailbox
                    else:
                        print("MESSAGE WRITTEN TO FILE")
                        self._create_message("250 OK")
                        self._state = "RSET"
                else:
                    self._create_message("501: SYNTAX ERROR IN PARAMETERS OR ARGUMENTS (EMPTY ADDRESS)")
                    print("NO ADDRESS TO WRITE")
            else:
                self._create_message("503: BAD SEQUENCE OF COMMANDS")
                print("COMMAND INVALID")

        elif command == "RSET":
            # Clears client data and resets state.
            self._client_recipient = ""
            self._client_sent_from = ""
            self._state == "HELO"
            self._create_message("250 OK")
            print("STATE RESET")

        elif command == "QUIT":
            # Closes.
            self._create_message("221 SERVICE CLOSING")
            print("QUITTING")
            self.close()

        elif command == "HELP":
            self._create_message(f"214 This is a help message: {self._commandlist}")
            print("RECEIVED A HELP")
        else:
            self._create_message("500 INVALID COMMAND")
            print("UNKNOWN COMMAND")

    def close(self):
        print("closing connection to", self._addr)
        try:
            self._selector.unregister(self._sock)
        except Exception as e:
            print(
                f"error: selector.unregister() exception for",
                f"{self._addr}: {repr(e)}",
            )
        try:
            self._sock.close()
        except OSError as e:
            print(
                f"error: socket.close() exception for",
                f"{self._addr}: {repr(e)}",
            )
        finally:
            # Delete reference to socket object for garbage collection
            self._sock = None

