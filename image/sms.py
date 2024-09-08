import os
import io
import paramiko
from google.cloud import pubsub_v1
from google.oauth2 import service_account
import json
from concurrent.futures import TimeoutError

# Retrieve the service account JSON from the environment variable
sa_key_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")

if not sa_key_json:
    raise ValueError("Service account key not found in the environment variable.")

# Convert the JSON string to a dictionary
sa_key_dict = json.loads(sa_key_json)

# Create credentials using the loaded service account key JSON
credentials = service_account.Credentials.from_service_account_info(sa_key_dict)

# Google Cloud Pub/Sub subscription settings
project_id = os.environ.get("GOOGLE_PROJECT_NAME")
subscription_id = os.environ.get("PUBSUB_SUBSCRIPTION_NAME")
timeout = None  # Time to listen for messages. Set to None to listen indefinitely.

# SSH settings
ssh_host = os.environ.get("SSH_HOST")
ssh_port = 22
ssh_user = os.environ.get("SSH_USER")
ssh_private_key = os.environ.get("SSH_PRIVATE_KEY")
modem_port = os.environ.get("MODEM_PORT")
if not ssh_private_key:
    raise ValueError("SSH private key not found in the environment variable.")

def shrink_string(s):
    return s[:56] + '...' if len(s) > 59 else s

def process_message(phone_number, text_message):
    try:
        ssh_client = paramiko.SSHClient()
        ssh_client.load_system_host_keys()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Load private key from environment variable
        private_key_file = io.StringIO(ssh_private_key)
        private_key = paramiko.RSAKey.from_private_key(private_key_file)

        # Connect to the SSH server using the private key from memory
        ssh_client.connect(ssh_host, port=ssh_port, username=ssh_user, pkey=private_key)

        command = f"sms_tool -d {modem_port} send 48{phone_number} '{text_message}'"
        stdin, stdout, stderr = ssh_client.exec_command(command)

        output = stdout.read().decode()
        error = stderr.read().decode()

        if output:
            print(f"Command output: {output}")
        if error:
            print(f"Command error: {error}")

        ssh_client.close()
        return error == ""
    except paramiko.SSHException as e:
        print(f"SSH error: {e}")
        return False
    except Exception as e:
        print(f"Error processing the message: {e}")
        return False

def callback(message):
    try:
        data = json.loads(message.data.decode('utf-8'))
        phone_number = data.get('phone_number')
        text_message = shrink_string(data.get('text_message'))

        if phone_number and text_message:
            print(f"Received message for phone number: {phone_number}")

            success = process_message(phone_number, text_message)
            if success:
                message.ack()  # Acknowledge the message after successful processing
            else:
                print(f"Failed to process message for phone number: {phone_number}. Nack-ing the message.")
                message.nack()  # Negatively acknowledge if SSH fails
        else:
            print("Message is missing phone number or text message. Ignoring.")
            message.nack()
    except json.JSONDecodeError as e:
        print(f"JSON decoding error: {e}")
        message.ack()
    except Exception as e:
        print(f"Error in callback: {e}")
        message.nack()

def listen_for_messages():
    subscriber = pubsub_v1.SubscriberClient(credentials=credentials)
    subscription_path = subscriber.subscription_path(project_id, subscription_id)

    streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)
    print(f"Listening for messages on {subscription_path}...")

    try:
        streaming_pull_future.result(timeout=timeout)
    except TimeoutError:
        streaming_pull_future.cancel()
        streaming_pull_future.result()
    except Exception as e:
        print(f"An error occurred while listening for messages: {e}")
    finally:
        subscriber.close()

if __name__ == "__main__":
    try:
        listen_for_messages()
    except KeyboardInterrupt:
        print("Interrupted by user. Shutting down...")
    except Exception as e:
        print(f"An error occurred in the main loop: {e}")
