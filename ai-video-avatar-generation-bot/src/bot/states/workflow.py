from aiogram.fsm.state import State, StatesGroup


class Workflow(StatesGroup):
    choosing_type = State()
    selecting_avatar = State()
    greeting_recipient = State()
    greeting_occasion = State()
    greeting_details = State()
    source_choice = State()
    source_text = State()
    waiting_voice = State()
    confirming_transcript = State()
    correcting_transcript = State()
    rerecording_voice = State()
    review_text = State()
    text_correction = State()
    voice_correction = State()
    final_confirmation = State()
