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
        self._command_list = "\nCOMMANDS: " \
                             "\n--HELO " \
                             "\n--MAIL <domain> " \
                             "\n--RCPT <domain>" \
                             "\n--DATA (begins loop, end with '.')" \
                             "\n--RSET " \
                             "\n--NOOP " \
                             "\n--QUIT " \
                             "\n--HELP"
        self._state_reset = "Default"
        self._state = self._state_reset  # Start State
        self._write_to_mailbox = False
        self._helo_complete = False
        self._mail_complete = False
        self._rcpt_complete = False
        self._current_mailbox = ""
        self._mail_buffer = ""
        self._client_sent_from = ""
        self._client_recipient = ""

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

        if self._state != "DATA":
            if len(message) >= header_length:
                self._module_processor(message[0:header_length],
                                       message[header_length:])  # Separate command and message
            else:
                # handles invalid message header.
                self._create_message("500 INVALID COMMAND")
                print("UNKNOWN COMMAND")
        else:
            if self._write_to_mailbox:
                if message != ".":  # checks for CRLF, then adds message contents to a buffer.
                    self._mail_buffer = self._mail_buffer + "\r\n" + message
                else:
                    f = open("MailBox\\" + self._current_mailbox + ".txt",
                             "a+")  # writes buffer contents to file on CRLF.
                    f.write(self._mail_buffer + "\r\n")
                    f.close()
                    print("MESSAGE WRITTEN TO FILE")
                    self._create_message("250 OK")
                    self._create_message("Resetting...")
                    self._reset()  # Resets the mail transfer.

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
        if (_address_begin >= 0) and \
                (_address_at >= 0) and \
                (_address_end >= 0) and \
                (_address_begin < _address_at) and \
                (_address_at < _address_end):
            return True

    def _reset(self):
        # Clears client data and resets state.
        self._client_recipient = ""
        self._client_sent_from = ""
        self._state = self._state_reset
        self._write_to_mailbox = False
        self._helo_complete = False
        self._mail_complete = False
        self._rcpt_complete = False
        self._current_mailbox = ""
        self._mail_buffer = ""
        self._client_sent_from = ""
        self._client_recipient = ""
        self._create_message("250 OK")
        print("STATE RESET")

    # Commands Processed Here
    def _module_processor(self, command, message):

        command = command.upper()  # allow lower case commands

        if command == "NOOP":
            self._create_message("250 OK")
            print("Received a NOOP")

        elif command == "HELO":
            self._state = "HELO"
            self._create_message("250 OK")
            print("Received a HELO")
            self._helo_complete = True

        elif command == "MAIL":
            # Checks for a valid address, if so, stores sender address and moves to next state.
            self._state = "MAIL"
            if self._helo_complete:
                if self._validate_address(message):
                    self._client_sent_from = self._get_address(message)
                    self._create_message("250 OK")
                    print("SENT")
                    self._mail_complete = True
                else:
                    self._create_message("501: SYNTAX ERROR (BAD ADDRESS)")
                    print("ADDRESS INVALID")
            else:
                self._create_message("503: BAD SEQUENCE OF COMMANDS")
                print("INVALID COMMAND")

        elif command == "RCPT":
            # Similarly checks for valid address, and if so, stores the recipient address and moves to next state.
            self._state = "RCPT"
            if self._mail_complete:
                if self._validate_address(message):
                    self._client_recipient = self._get_address(message)
                    self._create_message("250 OK")
                    print("RECEIVED")
                    self._rcpt_complete = True
                else:
                    self._create_message("501: SYNTAX ERROR (BAD ADDRESS)")
                    print("ADDRESS INVALID")
            else:
                self._create_message("503: BAD SEQUENCE OF COMMANDS")
                print("INVALID COMMAND")

        elif command == "DATA":
            # Checks to see if there are valid addresses, then writes the message to mailbox and moves to next state.
            self._state = "DATA"
            if self._rcpt_complete:
                self._create_message("354: START MAIL INPUT; END WITH ""'.'""")
                # Create the txt file used to store each recipient's messages.
                self._current_mailbox = "Mail for " + self._mailbox_filename(self._client_recipient)
                f = open("MailBox\\" + self._current_mailbox + ".txt", "a+")
                f.write("FROM: " + self._client_sent_from + "\n")
                f.write("TO: " + self._client_recipient + "\n")
                f.close()
                # Set process response to defer from commands processing to filling the message buffer.
                self._write_to_mailbox = True
            else:
                self._create_message("503: BAD SEQUENCE OF COMMANDS")
                print("COMMAND INVALID")

        elif command == "RSET":
            self._reset()

        elif command == "QUIT":
            # Closes and resets buffers.
            self._client_recipient = ""
            self._client_sent_from = ""
            self._state = "Default"
            self._write_to_mailbox = False
            self._helo_complete = False
            self._mail_complete = False
            self._rcpt_complete = False
            self._current_mailbox = ""
            self._mail_buffer = ""
            self._client_sent_from = ""
            self._client_recipient = ""
            self._create_message("221 SERVICE CLOSING")
            print("QUITTING")
            self.close()

        elif command == "HELP":
            self._create_message("214 This is a help message: " + self._command_list)
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
