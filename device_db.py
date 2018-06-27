

def create_entangler(channel_offset=0, is_master=False):
    d = {}

    # Note these output / input channel functions are hard-coded into the core
    # so they cannot be easily reassigned.
    names = {
        # Outputs
        0: "_1092_fastsw",
        1: "_422sigma_fastsw",
        2: "_422pulsed_trigger",
        3: "ttl_entangler",
        # Inputs
        4: "apd_1",
        5: "apd_2",
        6: "_422pulsed_input"
    }

    for i in range(7):
        if i in names:
            name = names[i]
        else:
            continue
        d[name] = {
            "type": "local",
            "module": "artiq.coredevice.ttl",
            "class": "TTLOutput" if i < 4 else "TTLInput",
            "arguments": {"channel": channel_offset+i},
        }

    d["entangler"] = {
        "type": "local",
        "module": "artiq.coredevice.entangler",
        "class": "Entangler",
        "arguments": {"channel": channel_offset+7, "is_master": is_master},
    }
    return d