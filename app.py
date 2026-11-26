
import streamlit as st
from supabase import create_client
import bcrypt
from datetime import datetime, timedelta, timezone

# --------------------------------------------------
# PAGE SETTINGS
# --------------------------------------------------

st.set_page_config(
    page_title="Family Secret Santa",
    page_icon="🎄",
    layout="centered"
)

# --------------------------------------------------
# SUPABASE CONNECTION
# --------------------------------------------------

@st.cache_resource
def connect_to_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


try:
    supabase = connect_to_supabase()
except Exception:
    st.error(
        "We couldn't connect to the Secret Santa database. "
        "Please check the app configuration."
    )
    st.stop()


# --------------------------------------------------
# PARTICIPANTS AND SETTINGS
# --------------------------------------------------

PARTICIPANTS = [
    "Keegan",
    "Prayasta",
    "Sy",
    "Dawie",
    "Josh",
    "Kayleigh"
]

BUDGET = "R200"
MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


# --------------------------------------------------
# FESTIVE DESIGN
# --------------------------------------------------

st.markdown("""
<style>

.stApp {
    background-color: #fdf8ef;
}

.main .block-container {
    max-width: 750px;
    padding-top: 2rem;
    padding-bottom: 3rem;
}

h1, h2, h3 {
    color: #8b1e2d;
}

p, label, .stMarkdown {
    color: #3b4938;
}

div.stButton > button {
    background-color: #dce9d9;
    color: #284b35;
    border: 1px solid #c5dbc1;
    border-radius: 12px;
    padding: 0.6rem 1.5rem;
    font-weight: 600;
}

div.stButton > button:hover {
    background-color: #c5dbc1;
    color: #284b35;
    border-color: #a9c7a5;
}

div[data-testid="stForm"] {
    background-color: white;
    padding: 22px;
    border-radius: 15px;
    border: 1px solid #e8ddc9;
}

div[data-testid="stMetric"] {
    background-color: white;
    border: 1px solid #e8ddc9;
    padding: 15px;
    border-radius: 12px;
}

</style>
""", unsafe_allow_html=True)


# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "participant_id" not in st.session_state:
    st.session_state.participant_id = None

if "participant_name" not in st.session_state:
    st.session_state.participant_name = None

if "started" not in st.session_state:
    st.session_state.started = False


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def get_participant(name):
    result = (
        supabase.table("participants")
        .select("id, name, pin_hash")
        .eq("name", name)
        .limit(1)
        .execute()
    )

    if result.data:
        return result.data[0]

    return None


def get_login_attempt(participant_id):
    result = (
        supabase.table("login_attempts")
        .select("*")
        .eq("participant_id", participant_id)
        .limit(1)
        .execute()
    )

    if result.data:
        return result.data[0]

    return None


def record_failed_login(participant_id):
    now = datetime.now(timezone.utc)
    attempt = get_login_attempt(participant_id)

    if attempt:
        window_start = datetime.fromisoformat(
            attempt["window_started_at"].replace("Z", "+00:00")
        )

        if now - window_start > timedelta(minutes=LOCKOUT_MINUTES):
            failed_attempts = 0
            window_started = now
        else:
            failed_attempts = attempt["failed_attempts"]
            window_started = window_start
    else:
        failed_attempts = 0
        window_started = now

    failed_attempts += 1

    locked_until = None

    if failed_attempts >= MAX_ATTEMPTS:
        locked_until = (
            now + timedelta(minutes=LOCKOUT_MINUTES)
        ).isoformat()

    supabase.table("login_attempts").upsert({
        "participant_id": participant_id,
        "failed_attempts": failed_attempts,
        "window_started_at": window_started.isoformat(),
        "locked_until": locked_until
    }).execute()


def is_locked_out(participant_id):
    attempt = get_login_attempt(participant_id)

    if not attempt or not attempt["locked_until"]:
        return False

    locked_until = datetime.fromisoformat(
        attempt["locked_until"].replace("Z", "+00:00")
    )

    now = datetime.now(timezone.utc)

    if now < locked_until:
        return True

    # Lockout has expired; reset the attempts
    supabase.table("login_attempts").delete().eq(
        "participant_id", participant_id
    ).execute()

    return False


def clear_login_attempts(participant_id):
    supabase.table("login_attempts").delete().eq(
        "participant_id", participant_id
    ).execute()


def get_progress():
    result = (
        supabase.table("wishlists")
        .select("participant_id")
        .execute()
    )

    return len(result.data)


def has_submitted(participant_id):
    result = (
        supabase.table("wishlists")
        .select("participant_id")
        .eq("participant_id", participant_id)
        .limit(1)
        .execute()
    )

    return len(result.data) > 0


def submit_wishlist(participant_id, idea_1, idea_2, idea_3):
    return supabase.rpc(
        "submit_wishlist",
        {
            "p_participant_id": participant_id,
            "p_idea_1": idea_1,
            "p_idea_2": idea_2,
            "p_idea_3": idea_3
        }
    ).execute()


def get_my_draw(participant_id):
    result = (
        supabase.table("draws")
        .select("recipient_id")
        .eq("giver_id", participant_id)
        .limit(1)
        .execute()
    )

    if not result.data:
        return None

    recipient_id = result.data[0]["recipient_id"]

    recipient = (
        supabase.table("participants")
        .select("id, name")
        .eq("id", recipient_id)
        .limit(1)
        .execute()
    )

    if not recipient.data:
        return None

    wishlist = (
        supabase.table("wishlists")
        .select("idea_1, idea_2, idea_3")
        .eq("participant_id", recipient_id)
        .limit(1)
        .execute()
    )

    if not wishlist.data:
        return None

    return {
        "name": recipient.data[0]["name"],
        "ideas": [
            wishlist.data[0]["idea_1"],
            wishlist.data[0]["idea_2"],
            wishlist.data[0]["idea_3"]
        ]
    }


# --------------------------------------------------
# HOMEPAGE
# --------------------------------------------------

if not st.session_state.started and not st.session_state.logged_in:

    st.markdown(
        "<div style='text-align:center; padding-top:50px;'>"
        "<p style='font-size:55px;'>🎄</p>"
        "<h1 style='font-size:42px; color:#8b1e2d;'>"
        "Family Secret Santa"
        "</h1>"
        "<p style='font-size:20px; color:#3b4938;'>"
        "A little Christmas magic, a lot of surprises!"
        "</p>"
        "<p style='font-size:17px; color:#3b4938;'>"
        "The most wonderful time of the year is here. "
        "Let's make this Christmas extra special!"
        "</p>"
        "<p style='font-size:35px;'>🎁 ✨ 🎅</p>"
        "</div>",
        unsafe_allow_html=True
    )

    st.divider()

    st.markdown(
        "<p style='text-align:center; font-size:16px;'>"
        "Ready to find out who you're buying a gift for?"
        "</p>",
        unsafe_allow_html=True
    )

    if st.button("Let's Start! 🎄", use_container_width=True):
        st.session_state.started = True
        st.rerun()


# --------------------------------------------------
# LOGIN PAGE
# --------------------------------------------------

elif not st.session_state.logged_in:

    st.title("🎄 Family Secret Santa 🎄")

    st.markdown(
        "<div style='text-align:center;'>"
        "<p style='font-size:18px;'>"
        "A little Christmas magic, a lot of surprises!"
        "</p>"
        "</div>",
        unsafe_allow_html=True
    )

    st.divider()

    st.subheader("🎅 Welcome!")

    st.write("Please log in to access your Secret Santa page.")

    with st.form("login_form"):

        selected_name = st.selectbox(
            "Select your name",
            PARTICIPANTS
        )

        entered_pin = st.text_input(
            "Enter your 4-digit PIN",
            type="password",
            max_chars=4
        )

        login_button = st.form_submit_button(
            "Log In 🎄",
            use_container_width=True
        )

    if login_button:

        if len(entered_pin) != 4 or not entered_pin.isdigit():
            st.error("Please enter your 4-digit PIN.")

        else:
            try:
                participant = get_participant(selected_name)

                if not participant:
                    st.error("Login details could not be verified.")

                elif is_locked_out(participant["id"]):
                    st.error(
                        "Too many incorrect attempts. "
                        "Please wait 15 minutes before trying again."
                    )

                else:
                    pin_matches = bcrypt.checkpw(
                        entered_pin.encode("utf-8"),
                        participant["pin_hash"].encode("utf-8")
                    )

                    if pin_matches:

                        clear_login_attempts(participant["id"])

                        st.session_state.logged_in = True
                        st.session_state.participant_id = participant["id"]
                        st.session_state.participant_name = participant["name"]

                        st.rerun()

                    else:
                        record_failed_login(participant["id"])
                        st.error("Incorrect PIN. Please try again.")

            except Exception as e:
                st.error(
                    "Something went wrong during login. "
                    "Please try again."
                )
                st.exception(e)


# --------------------------------------------------
# PARTICIPANT DASHBOARD
# --------------------------------------------------

else:

    participant_id = st.session_state.participant_id
    participant_name = st.session_state.participant_name

    st.title("🎄 Family Secret Santa 🎄")

    st.subheader(f"Hello, {participant_name}! 🎄")

    st.write(
        f"Your Secret Santa gift budget is **{BUDGET}**."
    )

    st.divider()

    # Progress tracker
    submitted_count = get_progress()

    st.metric(
        "Wishlists submitted",
        f"{submitted_count} / 6"
    )

    st.progress(submitted_count / 6)

    st.write(
        f"{submitted_count} out of 6 family members "
        "have submitted their wishlists."
    )

    st.divider()

    # Check whether this participant has a draw
    my_draw = get_my_draw(participant_id)

    if my_draw:

        st.subheader("🎁 Your Secret Santa Draw!")

        st.success(
            "The draw is complete! Your recipient is..."
        )

        st.markdown(
            f"<h2 style='text-align:center; color:#8b1e2d;'>"
            f"🎄 {my_draw['name']} 🎄"
            f"</h2>",
            unsafe_allow_html=True
        )

        st.write(
            f"Here are {my_draw['name']}'s three gift ideas:"
        )

        for number, idea in enumerate(my_draw["ideas"], start=1):
            st.markdown(f"**Gift idea {number}:** {idea}")

        st.info(
            "Remember to keep your recipient a secret! 🤫"
        )

    else:

        already_submitted = has_submitted(participant_id)

        if already_submitted:

            st.subheader("⏳ Your wishlist is submitted!")

            st.success(
                "Thank you! Your wishlist has been saved."
            )

            st.write(
                "We're waiting for everyone else to submit "
                "their wishlists before revealing the draw."
            )

            st.info(
                "You can come back later to see who you drew."
            )

        else:

            st.subheader("🎁 Create Your Wishlist")

            st.write(
                "Add three gift ideas to help your Secret Santa."
            )

            st.caption(
                f"Please keep the budget of {BUDGET} in mind."
            )

            with st.form("wishlist_form"):

                idea_1 = st.text_input(
                    "Gift idea 1",
                    placeholder="What would you like?"
                )

                idea_2 = st.text_input(
                    "Gift idea 2",
                    placeholder="Another idea..."
                )

                idea_3 = st.text_input(
                    "Gift idea 3",
                    placeholder="One more idea..."
                )

                submit_button = st.form_submit_button(
                    "Submit My Wishlist 🎁",
                    use_container_width=True
                )

            if submit_button:

                if (
                    not idea_1.strip()
                    or not idea_2.strip()
                    or not idea_3.strip()
                ):

                    st.error(
                        "Please fill in all three gift ideas."
                    )

                else:
                    try:
                        result = submit_wishlist(
                            participant_id,
                            idea_1,
                            idea_2,
                            idea_3
                        )

                        st.success(
                            "Your wishlist has been submitted! 🎉"
                        )

                        st.rerun()

                    except Exception as e:
                        st.error(
                            "Your wishlist could not be submitted. "
                            "Please try again."
                        )
                        st.exception(e)


    st.divider()

    # Logout
    if st.button("Log Out", use_container_width=True):

        st.session_state.logged_in = False
        st.session_state.participant_id = None
        st.session_state.participant_name = None
        st.session_state.started = False

        st.rerun()


# --------------------------------------------------
# FOOTER
# --------------------------------------------------

st.divider()

st.markdown(
    "<div style='text-align:center;'>"
    "<p>Made with love & Christmas magic ❤️</p>"
    "</div>",
    unsafe_allow_html=True
)
