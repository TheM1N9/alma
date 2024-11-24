import os
import re
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import base64
import google.generativeai as genai
import logging
from typing import List, Dict, Any
import email.utils
from datetime import datetime, timezone
import json
from twikit import Client
import asyncio
from duckduckgo_search import DDGS


class GmailMonitor:
    def __init__(self, check_interval: int = 60):
        """Initialize Gmail Monitor with improved logging and tracking"""
        self.SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
        self.check_interval = check_interval
        self.service = None
        self.start_time = datetime.now(timezone.utc)

        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler("gmail_monitor.log"),
                logging.StreamHandler(),
            ],
        )
        self.logger = logging.getLogger(__name__)

        # Initialize empty list for processed messages
        self.processed_messages = []

        # Add Twitter credentials
        self.twitter_client = Client("en-US")
        self.twitter_username = os.getenv("USER_NAME", "")
        self.twitter_email = os.getenv("EMAIL", "")
        self.twitter_password = os.getenv("PASSWORD", "")

        # Initialize Twitter login state
        self.twitter_logged_in = False

        # Initialize both models
        self.model = self.setup_gemini()  # For email analysis

    def authenticate(self):
        """Authenticate with Gmail API using OAuth 2.0"""
        creds = None

        # Check if token.pickle exists with stored credentials
        if os.path.exists("token.pickle"):
            with open("token.pickle", "rb") as token:
                creds = pickle.load(token)

        # If credentials are invalid or don't exist, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    "credentials.json", self.SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save credentials for future use
            with open("token.pickle", "wb") as token:
                pickle.dump(creds, token)

        self.service = build("gmail", "v1", credentials=creds)

    def setup_gemini(self):
        """Setup regular Gemini model for email analysis"""
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        genai.configure(api_key=GEMINI_API_KEY)
        return genai.GenerativeModel("gemini-1.5-flash")

    def is_new_email(self, message_date_str: str) -> bool:
        """Check if email is newer than program start time"""
        try:
            message_date_tuple = email.utils.parsedate_tz(message_date_str)
            if message_date_tuple is None:
                return False
            message_date = datetime.fromtimestamp(
                email.utils.mktime_tz(message_date_tuple), timezone.utc
            )
            return message_date > self.start_time
        except Exception as e:
            print(f"Error parsing date {message_date_str}: {e}")
            return False

    def process_message(self, message_id: str) -> Dict[str, Any]:
        """Process a single message with improved error handling"""
        try:
            if self.service is None:
                raise Exception("Service not authenticated")

            msg_details = (
                self.service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

            headers = msg_details["payload"]["headers"]
            subject = next(
                (h["value"] for h in headers if h["name"].lower() == "subject"),
                "No Subject",
            )
            sender = next(
                (h["value"] for h in headers if h["name"].lower() == "from"),
                "Unknown Sender",
            )
            date = next(
                (h["value"] for h in headers if h["name"].lower() == "date"), None
            )

            # Skip if email is older than program start time
            if not date or not self.is_new_email(date):
                return {}

            # Get message body with improved parsing
            if "parts" in msg_details["payload"]:
                parts = msg_details["payload"]["parts"]
                content = self._get_message_body(parts)
            else:
                content = base64.urlsafe_b64decode(
                    msg_details["payload"]["body"].get("data", "")
                ).decode("utf-8")

            return {
                "id": message_id,
                "subject": subject,
                "sender": sender,
                "date": date,
                "content": content,
                "labels": msg_details["labelIds"],
            }

        except Exception as e:
            self.logger.error(f"Error processing message {message_id}: {e}")
            return {}

    def _get_message_body(self, parts: List[Dict]) -> str:
        """Recursively extract message body from parts"""
        body = ""
        for part in parts:
            if part["mimeType"] == "text/plain":
                if "data" in part["body"]:
                    body += base64.urlsafe_b64decode(part["body"]["data"]).decode(
                        "utf-8"
                    )
            elif "parts" in part:
                body += self._get_message_body(part["parts"])
        return body

    def analyze_email_type(self, model, email_data):
        """Analyze if an email is a newsletter using Gemini"""
        prompt = f"""
        Analyze this email and determine if it's a newsletter. Consider these aspects:
        - Subject: {email_data['subject']}
        - Sender: {email_data['sender']}
        - Content preview: {email_data['content']}
        
        Respond with 'NEWSLETTER' or 'NOT_NEWSLETTER' followed by a brief reason why. And if it's a newsletter, create a list of the topics discussed.
        The topics should be the main topics discussed in the email.
        If only a single topic was discussed in the newsletter then place only single topic in the list, don't break it down. 
        output in the following format:
        ```json
        {{
            "type": "NEWSLETTER" | "NOT_NEWSLETTER",
            "reason": "reason why it's a newsletter" | "reason why it's not a newsletter",
            "topics": ["topic1", "topic2", "topic3"] | []
        }}
        ```
        """

        try:
            response = model.generate_content(prompt)
            analysis = re.search("```json(.*)```", response.text, re.DOTALL)
            print(f"Analysis: {analysis}")
            if analysis:
                return analysis.group(1)
            else:
                return "ERROR: Could not parse JSON"
        except Exception as e:
            print(f"Error analyzing email: {e}")
            return "ERROR: Could not analyze"

    async def twitter_login(self):
        """Login to Twitter"""
        try:
            if not self.twitter_logged_in:
                await self.twitter_client.login(
                    auth_info_1=self.twitter_username,
                    auth_info_2=self.twitter_email,
                    password=self.twitter_password,
                )
                self.twitter_logged_in = True
                self.logger.info("Successfully logged in to Twitter!")
        except Exception as e:
            self.logger.error(f"Error logging in to Twitter: {str(e)}")
            raise e

    def search_topic(self, topic: str, num_results: int = 5) -> List[Dict]:
        """Search for topic information using DuckDuckGo"""
        try:
            print(f"\n🔎 Searching for information about: {topic}")
            results = []
            with DDGS() as ddgs:
                search_results = ddgs.text(
                    topic,
                    region="wt-wt",  # Worldwide results
                    safesearch="off",
                    timelimit="m",  # Last month
                    max_results=num_results,
                )
                results.extend(search_results)

            print(f"✅ Found {len(results)} search results")
            return results
        except Exception as e:
            print(f"❌ Error searching for topic: {e}")
            return []

    async def process_and_create_threads(self, email_data: Dict[str, str]):
        """Process email content and create threads for each topic"""
        try:
            print("\n=== Processing Email Content ===")

            # Step 1: Analyze email for topics
            print("📝 Analyzing email for topics...")
            analysis = self.analyze_email_type(self.model, email_data)

            analysis_data = json.loads(analysis)

            if analysis_data["type"] != "NEWSLETTER":
                print("❌ Not a newsletter, skipping thread creation")
                return

            topics = analysis_data["topics"]
            print(f"✅ Found {len(topics)} topics to discuss")

            # Step 2: Process each topic
            for topic in topics:
                try:
                    print(f"\n=== Processing Topic: {topic} ===")

                    # Step 3: Research the topic
                    print("🔎 Researching topic...")
                    search_results = self.search_topic(topic)

                    # Format research results
                    additional_info = (
                        "\n\n".join(
                            [
                                f"Title: {result['title']}\nContent: {result['body']}\nSource: {result['link']}"
                                for result in search_results
                            ]
                        )
                        if search_results
                        else "No additional information found."
                    )

                    # Step 4: Generate thread content
                    print("🤖 Generating thread content...")
                    prompt = f"""
                    Create an informative Twitter thread about: {topic}

                    Primary Newsletter Content:
                    {email_data['content']}

                    Additional Research:
                    {additional_info}

                    Requirements:
                    - Focus primarily on the newsletter content
                    - Start with a strong hook tweet
                    - Each tweet must be under 280 characters
                    - Include key points from the newsletter
                    - Add context from research when relevant
                    - Cite sources for additional information
                    - End with key takeaways
                    - Use emojis strategically
                    - Separate tweets with [TWEET]

                    Make it engaging and informative while prioritizing the newsletter's perspective.
                    """

                    response = self.model.generate_content(prompt)
                    print(f"Response: {response.text}")
                    tweets = response.text.split("[TWEET]")
                    tweets = [tweet.strip() for tweet in tweets if tweet.strip()]

                    # Add thread starter if needed
                    if not any("🧵" in tweet for tweet in tweets):
                        tweets.insert(
                            0, f"🚀 Latest on: {topic}\n\nA comprehensive thread 🧵"
                        )

                    print(f"📝 Generated {len(tweets)} tweets")

                    # Step 5: Post the thread
                    print("🐦 Posting thread to Twitter...")
                    success = await self.post_thread(tweets)

                    if success:
                        print(f"✅ Successfully posted thread about: {topic}")
                    else:
                        print(f"❌ Failed to post thread about: {topic}")

                    print("⏳ Waiting 30 seconds before next topic...")
                    await asyncio.sleep(30)

                except Exception as e:
                    print(f"❌ Error processing topic '{topic}': {e}")
                    continue

        except Exception as e:
            print(f"❌ Error in process_and_create_threads: {e}")

    async def post_thread(self, tweets: List[str]) -> bool:
        """Post a thread of tweets with improved formatting"""
        try:
            print("\n=== Posting Twitter Thread ===")
            previous_tweet_id = None

            for i, tweet in enumerate(tweets):
                print(f"\n🐦 Posting tweet {i+1}/{len(tweets)}")

                if i > 0 and i < len(tweets) - 1:
                    tweet = tweet.rstrip() + " ⤵️"
                elif i == len(tweets) - 1:
                    tweet = tweet.rstrip() + " 🔚"

                if previous_tweet_id:
                    response = await self.twitter_client.create_tweet(
                        text=tweet, reply_to=previous_tweet_id
                    )
                else:
                    response = await self.twitter_client.create_tweet(text=tweet)

                previous_tweet_id = response.id
                print("✅ Tweet posted successfully")

                print("⏳ Waiting 2 seconds before next tweet...")
                await asyncio.sleep(2)

            print("\n✅ Thread posted successfully!")
            return True

        except Exception as e:
            print(f"❌ Error posting thread: {str(e)}")
            return False

    async def monitor_inbox(self):
        """Monitor inbox for new emails only"""
        print("\n=== Starting Gmail Monitor ===")
        print(f"Start Time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print("Monitoring for new emails...\n")

        await self.twitter_login()
        print("✅ Twitter login successful")

        while True:
            try:
                print("\n🔄 Checking for new emails...")

                if self.service is None:
                    raise Exception("Service not authenticated")

                results = (
                    self.service.users()
                    .messages()
                    .list(userId="me", q="is:unread", labelIds=["INBOX"])
                    .execute()
                )

                messages = results.get("messages", [])

                if messages:
                    for message in messages:
                        message_id = message["id"]

                        # Skip if already processed
                        if message_id in self.processed_messages:
                            print(f"⏭️ Skipping already processed message: {message_id}")
                            continue

                        # Get message details
                        msg = (
                            self.service.users()
                            .messages()
                            .get(userId="me", id=message_id, format="full")
                            .execute()
                        )

                        # Check if it's a new email
                        headers = msg["payload"]["headers"]
                        date = next(
                            (
                                h["value"]
                                for h in headers
                                if h["name"].lower() == "date"
                            ),
                            None,
                        )

                        if date and self.is_new_email(date):
                            print(f"\n📩 Processing new email: {message_id}")
                            email_data = self.process_message(message_id)

                            if email_data:
                                # Process email and create threads
                                await self.process_and_create_threads(email_data)

                                # Mark as processed
                                self.processed_messages.append(message_id)
                                print(f"✅ Successfully processed email: {message_id}")
                        else:
                            print(f"⏭️ Skipping older email: {message_id}")
                            # Mark older emails as read
                            self.service.users().messages().modify(
                                userId="me",
                                id=message_id,
                                body={"removeLabelIds": ["UNREAD"]},
                            ).execute()

                print(
                    f"\n💤 Waiting {self.check_interval} seconds before next check..."
                )
                await asyncio.sleep(self.check_interval)

            except KeyboardInterrupt:
                print("\n⛔ Monitoring stopped by user")
                break
            except Exception as e:
                print(f"\n❌ Error: {str(e)}")
                await asyncio.sleep(10)


async def main():
    monitor = GmailMonitor()
    monitor.authenticate()
    await monitor.monitor_inbox()


if __name__ == "__main__":
    asyncio.run(main())
