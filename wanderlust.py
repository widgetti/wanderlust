import json
import os

import ipyleaflet
import openai

import solara

center_default = (53.2305799, 6.5323552)
zoom_default = 2

messages_default = []

messages = solara.reactive(messages_default)
zoom_level = solara.reactive(zoom_default)
center = solara.reactive(center_default)
markers = solara.reactive([])

url = ipyleaflet.basemaps.OpenStreetMap.Mapnik.build_url()
openai.api_key = os.getenv("OPENAI_API_KEY")
model = "gpt-4-1106-preview"


function_descriptions = [
    {
        "type": "function",
        "function": {
            "name": "update_map",
            "description": "Update map to center on a particular location",
            "parameters": {
                "type": "object",
                "properties": {
                    "longitude": {"type": "number", "description": "Longitude of the location to center the map on"},
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
                    "longitude": {"type": "number", "description": "Longitude of the location to the marker"},
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
    function = tool_call["function"]
    name = function["name"]
    arguments = json.loads(function["arguments"])
    return_value = functions[name](**arguments)
    message = {
        "role": "tool",
        "tool_call_id": tool_call["id"],
        "name": tool_call["function"]["name"],
        "content": return_value,
    }
    return message


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
            *[ipyleaflet.Marker.element(location=k["location"], draggable=False) for k in markers.value],
        ],
    )


@solara.component
def ChatInterface():
    prompt = solara.use_reactive("")

    def add_message(value: str):
        if value == "":
            return
        messages.set(messages.value + [{"role": "user", "content": value}])
        prompt.set("")

    def ask():
        if not messages.value:
            return
        last_message = messages.value[-1]
        if last_message["role"] == "user" or last_message["role"] == "tool":
            completion = openai.ChatCompletion.create(
                model=model,
                messages=messages.value,
                # Add function calling
                tools=function_descriptions,
                tool_choice="auto",
            )

            output = completion.choices[0].message
            print("received", output)
            try:
                handled_messages = handle_message(output)
                messages.value = [*messages.value, output, *handled_messages]

            except Exception as e:
                print("errr", e)

    def handle_message(message):
        print("handle", message)
        messages = []
        if message["role"] == "assistant":
            tools_calls = message.get("tool_calls", [])
            for tool_call in tools_calls:
                messages.append(ai_call(tool_call))
        return messages

    def handle_initial():
        print("handle initial", messages.value)
        for message in messages.value:
            handle_message(message)

    solara.use_effect(handle_initial, [])
    result = solara.use_thread(ask, dependencies=[messages.value])
    with solara.Column(style={"height": "100%"}):
        with solara.Column(style={"height": "100%", "overflow-y": "auto"}, classes=["chat-interface"]):
            for message in messages.value:
                if message["role"] == "user":
                    solara.Text(message["content"], classes=["chat-message", "user-message"])
                elif message["role"] == "assistant":
                    if message["content"]:
                        solara.Markdown(message["content"])
                    elif message["tool_calls"]:
                        solara.Markdown("*Calling map functions*")
                    else:
                        solara.Preformatted(repr(message), classes=["chat-message", "assistant-message"])
                elif message["role"] == "tool":
                    pass  # no need to display
                else:
                    solara.Preformatted(repr(message), classes=["chat-message", "assistant-message"])
                # solara.Text(message, classes=["chat-message"])
        with solara.Column():
            solara.InputText(
                label="Ask your ", value=prompt, style={"flex-grow": "1"}, on_value=add_message, disabled=result.state == solara.ResultState.RUNNING
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

    with solara.Column(style={"height": "100%"}):
        with solara.AppBar():
            solara.Button("Save", on_click=save)
            solara.Button("Load", on_click=load)
            solara.Button("Soft reset", on_click=reset_ui)
        with solara.Columns(style={"height": "100%"}):
            ChatInterface().key(f"chat-{reset_counter}")
            Map()  # .key(f"map-{reset_counter}")


# TODO: custom layout
# @solara.component
# def Layout(children):
#     with solara.v.AppBar():
#         with solara.Column(children=children):
#             pass
