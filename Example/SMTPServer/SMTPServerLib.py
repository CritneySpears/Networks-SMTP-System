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
        self._helo_received = False  # CHECK IF RECEIVED 'HELO' COMMAND
        self._mail_sender = ""
        self._mail_recipient = ""
        self._data_input = False  # CHECK TO SEE IF IN DATA INPUT STAGE

        self._incoming_buffer = queue.Queue()
        self._outgoing_buffer = queue.Queue()

        self.encryption = SMTPServerEncryption.nws_encryption()

        events = selectors.EVENT_READ | selectors.EVENT_WRITE
        self._selector.register(self._sock, events, data=None)


        # RE-CREATE MAILBOX FOLDER IF NONE EXIST
        if not path.exists("Mail Boxes"):
            os.mkdir("Mail Boxes")

    #
    #
    #

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

    #
    #
    #

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

    #
    #
    #

    def _write(self):
        try:
            message = self._outgoing_buffer.get_nowait()
        except:
            message = None

        if message:
            # print("sending", repr(message), "to", self._addr)
            try:
                sent = self._sock.send(message)
            except BlockingIOError:
                # Resource temporarily unavailable (errno EWOULDBLOCK)
                pass

    #
    #
    #

    def _create_message(self, content):
        encoded = self.encryption.encrypt(content)
        nwencoded = encoded.encode()
        self._outgoing_buffer.put(nwencoded)

    #
    #
    #

    def _process_response(self):
        message = self._incoming_buffer.get()
        header_length = 4
        if self._data_input:  # CHECK IF IN DATA INPUT STAGE
            if message != ".":  # CHECK FOR END OF DATA INPUT
                mailbox = self._mailbox_name(self._mail_recipient)  # GENERATE MAILBOX USING RECIPIENT EMAIL
                f = open("Mail Boxes\\" + mailbox + ".txt", "a+")  # OPEN MAILBOX
                f.write(message + "\n")  # WRITE TO MAILBOX
                f.close()  # CLOSE MAILBOX
            else:
                print("250: DATA SAVED FOR DELIVERY")
                self._create_message("250: DATA SAVED FOR DELIVERY\n")
                self._data_input = False  # END DATA INPUT STAGE
        elif len(message) >= header_length:  # REMOVES 4 CHARACTER COMMAND AND PROCESSES RESPONSE
            self._module_processor(message[0:header_length], message[header_length:])

    #
    #
    #

    def _mailbox_name(self, addr):
        file_name = ""
        for x in addr:
            if x == "@":
                file_name += "-"
            elif x == ".":
                file_name += "_"
            else:
                file_name += x
        return file_name

    def _is_valid_mailbox(self, message):
        is_valid = False  #
        if self._validate_address(message):
            print(message)
            addr = self._get_address(message)
            print(addr)
            file = open("domainNames.txt", "r")
            for x in file:
                x = x.strip()
                print(x)
                if addr == x:
                    is_valid = True
            file.close()
        return is_valid

    def _validate_address(self, message):
        _string = str(message)
        _string_start = _string.find("<")
        _string_end = _string.find(">")
        _string_at = _string.find("@")
        #
        #
        #
        return (_string_start >= 0) and (_string_at >= 0) and (_string_end >= 0) and \
               (_string_start < _string_at) and (_string_at < _string_end)


    def _get_address(self, message):
        _string = str(message)
        _string_start = _string.find("<")
        _string_end = _string.find(">")
        if (_string_start >= 0) and (_string_end >= 0) and (_string_end > _string_start):  # CHECK FOR BRACKETS
            return message[_string_start + 1:_string_end]
        else:
            return ""

    #
    #
    #

    def _module_processor(self, command, message):

        # command = command.upper()  # SET ALL INCOMING MESSAGES TO UPPERCASE

        if command == "NOOP":
            print("RECEIVED A 'NOOP'")
            self._create_message("250: OK")

        elif command == "HELO":
            print("RECEIVED A 'HELO'")
            self._create_message("250: OK".format(self._addr))
            self._helo_received = True  # SETS BOOL TO TRUE SO USER CAN PROGRESS THROUGH SYSTEM

        elif command == "MAIL":
            if self._helo_received:  # CHECK TO SEE IF 'HELO' REQUEST RECEIVED
                if "FROM:" in message and self._validate_address(message):  # IF 'FROM:' FOUND, VALIDATE ADDRESS
                    self._mail_sender = self._get_address(message)  # SET SENDER ADDRESS TO ADDRESS IN MESSAGE
                    print("SENDER OK")
                    self._create_message("250: SENDER OK".format(self._mail_sender))
                else:
                    print("INVALID ADDRESS")
                    self._create_message("510: INVALID ADDRESS")  # ADDRESS NOT RECOGNISED
            else:
                print("INVALID COMMAND")
                self._create_message("503: INVALID COMMAND")  # 'HELO' NOT RECEIVED

        elif command == "RCPT":
            if self._helo_received:
                if "TO:" in message and self._validate_address(message):
                    self._mail_recipient = self._get_address(message)
                    print("RECIPIENT OK")
                    self._create_message("250: RECIPIENT OK".format(self._mail_recipient))
                else:
                    print("INVALID ADDRESS")
                    self._create_message("510: INVALID ADDRESS")  # ADDRESS NOT RECOGNISED
            else:
                print("INVALID COMMAND")
                self._create_message("503: INVALID COMMAND")  # 'HELO' NOT RECEIVED

        elif command == "DATA":
            if self._helo_received:
                if self._mail_sender != "" and self._mail_recipient != "":  # ONLY ACCEPT DATA WITH SENDER & RECIPIENT
                    self._create_message("354: ENTER MAIL")
                    self._create_message("354: FINISH DATA ENTRY WITH A ""'.'"" ON A BLANK LINE")
                    self._data_input = True  # ENTER DATA INPUT STAGE
                    mailbox = self._mailbox_name(self._mail_recipient)  # GENERATE MAILBOX USING RECIPIENT ADDRESS
                    f = open("Mail Boxes\\" + mailbox + ".txt", "a+")
                    f.write("FROM: " + self._mail_sender + "\n")  # FILL SENDER ADDRESS
                    f.write("TO: " + self._mail_recipient + "\n")  # FILL RECIPIENT ADDRESS
                    f.close()  # CLOSE OUT OF MAILBOX
                else:
                    self._create_message("503: INVALID COMMAND")  # MUST INPUT 'RCPT' BEFORE 'DATA'
            else:
                self._create_message("503: INVALID COMMAND")  # NO 'HELO' REQUEST

        elif command == "RSET":
            print("DATA RESETTING")
            self._create_message("250: DATA RESET")

            # SET VARIABLES TO DEFAULT VALUES
            self._helo_received = False
            self._mail_sender = ""
            self._mail_recipient = ""
            self._data_input = False

        elif command == "HELP":
            print("RECEIVED A 'HELP'")
            self._create_message("214: HELP GUIDE - https://tools.ietf.org/html/rfc5321")

        elif command == "QUIT":
            print("RECEIVED 'QUIT' - CLOSING")
            self._create_message("SESSION CLOSING")
            self.close()

        else:
            self._create_message("500: UNKNOWN COMMAND")
            print("RECEIVED AN UNKNOWN COMMAND")

    #
    #
    #

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

