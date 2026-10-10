# EQ Juggler (MVP)
Load different EQ presets (in APO syntax) and compare them. Presets are loudness matched automatically.
By now you need to manually set it and program's capabilities are limited because it's MVP. You also need to manually connect Pipewire's node of EQ Juggler between some stream or source (or make EQ Juggler to act as default sink) to desired sink (headphones output, audio interface, Bluetooth, etc.). Program is only intended to be used with Pipewire and pipewire-jack as it is work as Jack client.
What it can do now:
* Apply different EQ presets to incoming audio stream from some node\[s\] and output it to other node\[s\]
* Loudness match all EQ presets so their perceived loudness is the same
* Change between EQ presets seamlessly

## Installation
```bash
pip install -r requirements.txt
pip install pyloudnorm
```

## How to setup
There are 2 blocks of comments on line 52 and line 69 of `main.py` that will help you with specifying your EQ presets and modifying loudness match strategy if you need to.

## How to run
```bash
python main.py
```

And wait for GUI window to appear (it can take some time). Then connect EQ Juggler's node between some source/stream and sink. Node's name is "EQ Juggler". If you will launch another instance of the program, then it will have postfix containing _pid_ that running that instance. By the way, you can make it more convenient to gather all streams (from browser, player, etc.) to EQ Jugglers node. Create new default sink "All Sources Hub":
```bash
pw-cli create-node adapter '{ factory.name=support.null-audio-sink node.name="Mixed-Input" node.description="All Sources Hub" media.class=Audio/Sink object.linger=true audio.position=[ FL FR ] }'
```
Then you can connect outports of "All Sources Hub" to inports of EQ Juggler.

![Node routing example](./assets/node-routing-example.png)
