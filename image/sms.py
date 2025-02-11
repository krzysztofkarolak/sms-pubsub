import os
import io
import paramiko
import subprocess
from google.cloud import pubsub_v1
from google.oauth2 import service_account
import json
from concurrent.futures import TimeoutError
import threading
import time
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

sa_key_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
if not sa_key_json:
    raise ValueError("Service account key not found in the environment variable.")

sa_key_dict = json.loads(sa_key_json)
credentials = service_account.Credentials.from_service_account_info(sa_key_dict)

project_id = os.environ.get("GOOGLE_PROJECT_NAME")
subscription_id = os.environ.get("PUBSUB_SUBSCRIPTION_NAME")
timeout = None
lock = threading.Lock()

# Connection settings
ssh_host = os.environ.get("SSH_HOST")
ssh_port = 22
ssh_user = os.environ.get("SSH_USER")
ssh_private_key = os.environ.get("SSH_PRIVATE_KEY")
modem_port = os.environ.get("MODEM_PORT")
send_mode = os.environ.get("SEND_MODE")
char_limit = int(os.environ.get("CHAR_LIMIT"))
if not ssh_private_key and send_mode == "ssh":
    raise ValueError("SSH private key not found in the environment variable.")

def shrink_string(s):
    return s[:char_limit] + '...' if len(s) > char_limit else s

def process_message_ssh(phone_number, text_message):
    try:
        ssh_client = paramiko.SSHClient()
        ssh_client.load_system_host_keys()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        private_key_file = io.StringIO(ssh_private_key)
        private_key = paramiko.RSAKey.from_private_key(private_key_file)

        ssh_client.connect(ssh_host, port=ssh_port, username=ssh_user, pkey=private_key, timeout=10)

        command = f"sms_tool -d {modem_port} send 48{phone_number} '{text_message}'"
        stdin, stdout, stderr = ssh_client.exec_command(command)

        output = stdout.read().decode()
        error = stderr.read().decode()

        if output:
            logging.info(f"Command output: {output}")
        if error:
            logging.error(f"Command error: {error}")
            return False

        ssh_client.close()
        return error == ""
    except paramiko.SSHException as e:
        logging.error(f"SSH error: {e}")
        return False
    except Exception as e:
        logging.error(f"Error processing the message: {e}")
        return False
    
def process_message_hilink(phone_number, text_message):
    command = f"hlcli smssend -to={phone_number} -msg='{text_message}'"
    try:
        result = subprocess.run(command, shell=True, check=True, text=True, capture_output=True)

        output = result.stdout.strip()
        error = result.stderr.strip()

        if output:
            logging.info(f"Success:\n{output}")
        if error:
            logging.error(f"Error:\n{error}")

        return not error
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed with error:\n{e.stderr}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return False

def callback(message):
    with lock:
        try:
            data = json.loads(message.data.decode('utf-8'))
            phone_number = data.get('phone_number')
            text_message = shrink_string(data.get('text_message'))

            if phone_number and text_message:
                logging.info(f"Received message for phone number: {phone_number}")

                process_message = process_message_hilink if send_mode == "hilink" else process_message_ssh
                success = process_message(phone_number, text_message)
                if success:
                    message.ack()  # Acknowledge the message after successful processing
                else:
                    logging.error(f"Failed to process message for phone number: {phone_number}. Nack-ing the message.")
                    message.nack()  # Negatively acknowledge if SSH fails
            else:
                logging.error("Message is missing phone number or text message. Ignoring.")
                message.nack()
        except json.JSONDecodeError as e:
            logging.error(f"JSON decoding error: {e}")
            message.ack()
        except Exception as e:
            logging.error(f"Error in callback: {e}")
            message.nack()

        time.sleep(5)

def listen_for_messages():
    subscriber = pubsub_v1.SubscriberClient(credentials=credentials)
    subscription_path = subscriber.subscription_path(project_id, subscription_id)

    streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)
    logging.info(f"Listening for messages on {subscription_path}...")

    try:
        streaming_pull_future.result(timeout=timeout)
    except TimeoutError:
        streaming_pull_future.cancel()
        streaming_pull_future.result()
    except Exception as e:
        logging.error(f"An error occurred while listening for messages: {e}")
    finally:
        subscriber.close()

if __name__ == "__main__":
    try:
        listen_for_messages()
    except KeyboardInterrupt:
        logging.error("Interrupted by user. Shutting down...")
    except Exception as e:
        logging.error(f"An error occurred in the main loop: {e}")
