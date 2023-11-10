import json
import os
import time
from pathlib import Path

import ipyleaflet
from openai import NotFoundError, OpenAI
from openai.types.beta import Thread

import solara

HERE = Path(__file__).parent

center_default = (0, 0)
zoom_default = 2

messages = solara.reactive([])
zoom_level = solara.reactive(zoom_default)
center = solara.reactive(center_default)
markers = solara.reactive([])

url = ipyleaflet.basemaps.OpenStreetMap.Mapnik.build_url()
openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
model = "gpt-4-1106-preview"
app_style = (HERE / "style.css").read_text()


# Declare tools for openai assistant to use
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


def assistant_tool_call(tool_call):
    # actually executes the tool call the OpenAI assistant wants to perform
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
    ipyleaflet.Map.element(  # type: ignore
        zoom=zoom_level.value,
        center=center.value,
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
def ChatMessage(message):
    with solara.Row(style={"align-items": "flex-start"}):
        # Catch "messages" that are actually tool calls
        if isinstance(message, dict):
            icon = "mdi-map" if message["output"] == "Map updated" else "mdi-map-marker"
            solara.v.Icon(children=[icon], style_="padding-top: 10px;")
            solara.Markdown(message["output"])
        elif message.role == "user":
            solara.Text(message.content[0].text.value, style={"font-weight": "bold;"})
        elif message.role == "assistant":
            if message.content[0].text.value:
                solara.v.Icon(
                    children=["mdi-compass-outline"], style_="padding-top: 10px;"
                )
                solara.Markdown(message.content[0].text.value)
            elif message.content.tool_calls:
                solara.v.Icon(children=["mdi-map"], style_="padding-top: 10px;")
                solara.Markdown("*Calling map functions*")
            else:
                solara.v.Icon(
                    children=["mdi-compass-outline"], style_="padding-top: 10px;"
                )
                solara.Preformatted(repr(message))
        else:
            solara.v.Icon(children=["mdi-compass-outline"], style_="padding-top: 10px;")
            solara.Preformatted(repr(message))


@solara.component
def ChatBox(children=[]):
    # this uses a flexbox with column-reverse to reverse the order of the messages
    # if we now also reverse the order of the messages, we get the correct order
    # but the scroll position is at the bottom of the container automatically
    with solara.Column(style={"flex-grow": "1"}):
        solara.Style(
            """
            .chat-box > :last-child{
                padding-top: 7.5vh;
            }
            """
        )
        # The height works effectively as `min-height`, since flex will grow the container to fill the available space
        solara.Column(
            style={
                "flex-grow": "1",
                "overflow-y": "auto",
                "height": "100px",
                "flex-direction": "column-reverse",
            },
            classes=["chat-box"],
            children=list(reversed(children)),
        )


@solara.component
def ChatInterface():
    prompt = solara.use_reactive("")
    run_id: solara.Reactive[str] = solara.use_reactive(None)

    # Create a thread to hold the conversation only once when this component is created
    thread: Thread = solara.use_memo(openai.beta.threads.create, dependencies=[])

    def add_message(value: str):
        if value == "":
            return
        prompt.set("")
        new_message = openai.beta.threads.messages.create(
            thread_id=thread.id, content=value, role="user"
        )
        messages.set([*messages.value, new_message])
        # this creates a new run for the thread
        # also also triggers a rerender (since run_id.value changes)
        # which will trigger the poll function blow to start in a thread
        run_id.value = openai.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id="asst_RqVKAzaybZ8un7chIwPCIQdH",
            tools=tools,
        ).id

    def poll():
        if not run_id.value:
            return
        completed = False
        while not completed:
            try:
                run = openai.beta.threads.runs.retrieve(
                    run_id.value, thread_id=thread.id
                )
            # Above will raise NotFoundError when run creation is still in progress
            except NotFoundError:
                continue
            if run.status == "requires_action":
                tool_outputs = []
                for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                    tool_output = assistant_tool_call(tool_call)
                    tool_outputs.append(tool_output)
                    messages.set([*messages.value, tool_output])
                openai.beta.threads.runs.submit_tool_outputs(
                    thread_id=thread.id,
                    run_id=run_id.value,
                    tool_outputs=tool_outputs,
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

    # run/restart a thread any time the run_id changes
    result = solara.use_thread(poll, dependencies=[run_id.value])

    # Create DOM for chat interface
    with solara.Column(classes=["chat-interface"]):
        if len(messages.value) > 0:
            with ChatBox():
                for message in messages.value:
                    ChatMessage(message)

        with solara.Column():
            solara.InputText(
                label="Where do you want to go?"
                if len(messages.value) == 0
                else "Ask more question here",
                value=prompt,
                style={"flex-grow": "1"},
                on_value=add_message,
                disabled=result.state == solara.ResultState.RUNNING,
            )
            solara.ProgressLinear(result.state == solara.ResultState.RUNNING)
            if result.state == solara.ResultState.ERROR:
                solara.Error(repr(result.error))


@solara.component
def Page():
    with solara.Column(
        classes=["ui-container"],
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
            with solara.Row(
                gap="30px",
                style={"align-items": "center"},
                classes=["link-container"],
                justify="end",
            ):
                with solara.Row(gap="5px", style={"align-items": "center"}):
                    solara.Text("Source Code:", style="font-weight: bold;")
                    # target="_blank" links are still easiest to do via ipyvuetify
                    with solara.v.Btn(
                        icon=True,
                        tag="a",
                        attributes={
                            "href": "https://github.com/widgetti/wanderlust",
                            "title": "Wanderlust Source Code",
                            "target": "_blank",
                        },
                    ):
                        solara.v.Icon(children=["mdi-github-circle"])
                with solara.Row(gap="5px", style={"align-items": "center"}):
                    solara.Text("Powered by Solara:", style="font-weight: bold;")
                    with solara.v.Btn(
                        icon=True,
                        tag="a",
                        attributes={
                            "href": "https://solara.dev/",
                            "title": "Solara",
                            "target": "_blank",
                        },
                    ):
                        solara.HTML(
                            tag="img",
                            attributes={
                                "src": "https://solara.dev/static/public/logo.svg",
                                "width": "24px",
                            },
                        )
                    with solara.v.Btn(
                        icon=True,
                        tag="a",
                        attributes={
                            "href": "https://github.com/widgetti/solara",
                            "title": "Solara Source Code",
                            "target": "_blank",
                        },
                    ):
                        solara.v.Icon(children=["mdi-github-circle"])

        with solara.Row(
            justify="space-between", style={"flex-grow": "1"}, classes=["container-row"]
        ):
            ChatInterface()
            with solara.Column(classes=["map-container"]):
                Map()

        solara.Style(app_style)
