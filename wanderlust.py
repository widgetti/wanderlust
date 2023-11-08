import json
import os

import ipyleaflet
from openai import OpenAI, NotFoundError
from openai.types.beta import Thread
from openai.types.beta.threads import Run

import time

import solara

center_default = (0, 0)
zoom_default = 2

messages_default = []

messages = solara.reactive(messages_default)
zoom_level = solara.reactive(zoom_default)
center = solara.reactive(center_default)
markers = solara.reactive([])

url = ipyleaflet.basemaps.OpenStreetMap.Mapnik.build_url()
openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
model = "gpt-4-1106-preview"


tools = [
    {
        "type": "function",
        "function": {
            "name": "update_map",
            "description": "Update map to center on a particular location",
            "parameters": {
                "type": "object",
                "properties": {
                    "longitude": {
                        "type": "number",
                        "description": "Longitude of the location to center the map on",
                    },
                    "latitude": {
                        "type": "number",
                        "description": "Latitude of the location to center the map on",
                    },
                    "zoom": {
                        "type": "integer",
                        "description": "Zoom level of the map",
                    },
                },
                "required": ["longitude", "latitude", "zoom"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_marker",
            "description": "Add marker to the map",
            "parameters": {
                "type": "object",
                "properties": {
                    "longitude": {
                        "type": "number",
                        "description": "Longitude of the location to the marker",
                    },
                    "latitude": {
                        "type": "number",
                        "description": "Latitude of the location to the marker",
                    },
                    "label": {
                        "type": "string",
                        "description": "Text to display on the marker",
                    },
                },
                "required": ["longitude", "latitude", "label"],
            },
        },
    },
]


def update_map(longitude, latitude, zoom):
    print("update_map", longitude, latitude, zoom)
    center.set((latitude, longitude))
    zoom_level.set(zoom)
    return "Map updated"


def add_marker(longitude, latitude, label):
    markers.set(markers.value + [{"location": (latitude, longitude), "label": label}])
    return "Marker added"


functions = {
    "update_map": update_map,
    "add_marker": add_marker,
}


def ai_call(tool_call):
    function = tool_call.function
    name = function.name
    arguments = json.loads(function.arguments)
    return_value = functions[name](**arguments)
    tool_outputs = {
        "tool_call_id": tool_call.id,
        "output": return_value,
    }
    return tool_outputs


@solara.component
def Map():
    print("Map", zoom_level.value, center.value, markers.value)
    ipyleaflet.Map.element(  # type: ignore
        zoom=zoom_level.value,
        # on_zoom=zoom_level.set,
        center=center.value,
        # on_center=center.set,
        scroll_wheel_zoom=True,
        layers=[
            ipyleaflet.TileLayer.element(url=url),
            *[
                ipyleaflet.Marker.element(location=k["location"], draggable=False)
                for k in markers.value
            ],
        ],
    )


@solara.component
def ChatInterface():
    prompt = solara.use_reactive("")
    run_id: solara.Reactive[str] = solara.use_reactive(None)

    thread: Thread = solara.use_memo(openai.beta.threads.create, dependencies=[])
    print("thread id:", thread.id)

    def add_message(value: str):
        if value == "":
            return
        prompt.set("")
        new_message = openai.beta.threads.messages.create(
            thread_id=thread.id, content=value, role="user"
        )
        messages.set([*messages.value, new_message])
        run_id.value = openai.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id="asst_RqVKAzaybZ8un7chIwPCIQdH",
            tools=tools,
        ).id
        print("Run id:", run_id.value)

    def poll():
        if not run_id.value:
            return
        completed = False
        while not completed:
            try:
                run = openai.beta.threads.runs.retrieve(
                    run_id.value, thread_id=thread.id
                )  # When run is complete
                print("run", run.status)
            except NotFoundError:
                print("run not found (Yet)")
                continue
            if run.status == "requires_action":
                for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                    tool_output = ai_call(tool_call)
                    openai.beta.threads.runs.submit_tool_outputs(
                        thread_id=thread.id,
                        run_id=run_id.value,
                        tool_outputs=[tool_output],
                    )
            if run.status == "completed":
                messages.set(
                    [
                        *messages.value,
                        openai.beta.threads.messages.list(thread.id).data[0],
                    ]
                )
                run_id.set(None)
                completed = True
            time.sleep(0.1)
        retrieved_messages = openai.beta.threads.messages.list(thread_id=thread.id)
        messages.set(retrieved_messages.data)

    result = solara.use_thread(poll, dependencies=[run_id.value])

    def handle_message(message):
        print("handle", message)
        messages = []
        if message.role == "assistant":
            tools_calls = message.get("tool_calls", [])
            for tool_call in tools_calls:
                messages.append(ai_call(tool_call))
        return messages

    def handle_initial():
        print("handle initial", messages.value)
        for message in messages.value:
            handle_message(message)

    solara.use_effect(handle_initial, [])
    # result = solara.use_thread(ask, dependencies=[messages.value])
    with solara.Column(
        style={
            "height": "100%",
            "width": "38vw",
            "justify-content": "center",
            "background": "linear-gradient(0deg, transparent 75%, white 100%);",
        },
        classes=["chat-interface"],
    ):
        if len(messages.value) > 0:
            # The height works effectively as `min-height`, since flex will grow the container to fill the available space
            with solara.Column(
                style={
                    "flex-grow": "1",
                    "overflow-y": "auto",
                    "height": "100px",
                    "flex-direction": "column-reverse",
                }
            ):
                for message in reversed(messages.value):
                    with solara.Row(style={"align-items": "flex-start"}):
                        if message.role == "user":
                            solara.Text(
                                message.content[0].text.value,
                                classes=["chat-message", "user-message"],
                            )
                            assert len(message.content) == 1
                        elif message.role == "assistant":
                            if message.content[0].text.value:
                                solara.v.Icon(
                                    children=["mdi-compass-outline"],
                                    style_="padding-top: 10px;",
                                )
                                solara.Markdown(message.content[0].text.value)
                            elif message.content.tool_calls:
                                solara.v.Icon(
                                    children=["mdi-map"],
                                    style_="padding-top: 10px;",
                                )
                                solara.Markdown("*Calling map functions*")
                            else:
                                solara.v.Icon(
                                    children=["mdi-compass-outline"],
                                    style_="padding-top: 10px;",
                                )
                                solara.Preformatted(
                                    repr(message),
                                    classes=["chat-message", "assistant-message"],
                                )
                        elif message["role"] == "tool":
                            pass  # no need to display
                        else:
                            solara.v.Icon(
                                children=["mdi-compass-outline"],
                                style_="padding-top: 10px;",
                            )
                            solara.Preformatted(
                                repr(message),
                                classes=["chat-message", "assistant-message"],
                            )
                        # solara.Text(message, classes=["chat-message"])
        with solara.Column():
            solara.InputText(
                label="Ask your question here",
                value=prompt,
                style={"flex-grow": "1"},
                on_value=add_message,
                disabled=result.state == solara.ResultState.RUNNING,
            )
            solara.ProgressLinear(result.state == solara.ResultState.RUNNING)
            if result.state == solara.ResultState.ERROR:
                solara.Error(repr(result.error))
            # solara.Text("Thinking...")
            # solara.Button("Send", on_click=lambda: messages.set(messages.value + [message_input.value]))


@solara.component
def Page():
    reset_counter, set_reset_counter = solara.use_state(0)
    print("reset", reset_counter, f"chat-{reset_counter}")

    def reset_ui():
        set_reset_counter(reset_counter + 1)

    def save():
        with open("log.json", "w") as f:
            json.dump(messages.value, f)

    def load():
        with open("log.json", "r") as f:
            messages.set(json.load(f))
        reset_ui()

    with solara.Column(
        style={
            "height": "95vh",
            "justify-content": "center",
            "padding": "45px 50px 75px 50px",
        },
        gap="5vh",
    ):
        with solara.Row(justify="space-between"):
            with solara.Row(gap="10px", style={"align-items": "center"}):
                solara.v.Icon(children=["mdi-compass-rose"], size="36px")
                solara.HTML(
                    tag="h2",
                    unsafe_innerHTML="Wanderlust",
                    style={"display": "inline-block"},
                )
            # with solara.Row(gap="10px"):
            #     solara.Button("Save", on_click=save)
            #     solara.Button("Load", on_click=load)
            #     solara.Button("Soft reset", on_click=reset_ui)
        with solara.Row(justify="space-between", style={"flex-grow": "1"}):
            ChatInterface().key(f"chat-{reset_counter}")
            with solara.Column(style={"width": "50vw", "justify-content": "center"}):
                Map()  # .key(f"map-{reset_counter}")

        solara.Style(
            """
            .jupyter-widgets.leaflet-widgets{
                height: 100%;
                border-radius: 20px;
            }
            .solara-autorouter-content{
                display: flex;
                flex-direction: column;
                justify-content: stretch;
            }
            .v-toolbar__title{
                display: flex;
                align-items: center;
                column-gap: 0.5rem;
            }
            """
        )


# TODO: custom layout
# @solara.component
# def Layout(children):
#     with solara.v.AppBar():
#         with solara.Column(children=children):
#             pass
