"""Ask a real local OpenAI-compatible model for a validated, preview-only plan."""
import argparse
import json
import math
from urllib.request import ProxyHandler, Request, build_opener


# These are the same bounded action types understood by the Playground sequencer.
STEP_SCHEMA = {"anyOf": [
    {"type": "object", "properties": {"type": {"const": "led"},
     "value": {"type": "integer", "minimum": 0, "maximum": 255}},
     "required": ["type", "value"], "additionalProperties": False},
    {"type": "object", "properties": {"type": {"const": "joint"},
     "joint": {"enum": ["base", "shoulder", "elbow", "gripper"]},
     "delta": {"type": "number", "minimum": -20, "maximum": 20}},
     "required": ["type", "joint", "delta"], "additionalProperties": False},
    {"type": "object", "properties": {"type": {"const": "wait"},
     "seconds": {"type": "number", "minimum": 0, "maximum": 5}},
     "required": ["type", "seconds"], "additionalProperties": False},
    {"type": "object", "properties": {"type": {"const": "greet"}},
     "required": ["type"], "additionalProperties": False},
]}
PLAN_SCHEMA = {"type": "object", "properties": {
    "steps": {"type": "array", "items": STEP_SCHEMA, "maxItems": 12},
    "explanation": {"type": "string"}},
    "required": ["steps", "explanation"], "additionalProperties": False}
# Bind semantic model choices to this arm's measured/protocol direction convention.
# This compiler never reads the user's text and never creates a substitute plan.
DIRECTIONS = {"base": {"left": 1, "right": -1, "increase": 1, "decrease": -1},
              "shoulder": {"increase": 1, "decrease": -1},
              "elbow": {"up": -1, "down": 1, "increase": 1, "decrease": -1},
              "gripper": {"open": -1, "close": 1, "increase": 1, "decrease": -1}}
SEMANTIC_JOINTS = {direction: (joint, sign) for joint, directions in DIRECTIONS.items()
                   for direction, sign in directions.items() if direction not in ("increase", "decrease")}
MODEL_STEP_SCHEMA = {"anyOf": [STEP_SCHEMA["anyOf"][0],
    {"type": "object", "properties": {"type": {"const": "joint"},
     "direction": {"enum": list(SEMANTIC_JOINTS)},
     "degrees": {"type": "integer", "minimum": 0, "maximum": 20}},
     "required": ["type", "direction", "degrees"], "additionalProperties": False},
    {"type": "object", "properties": {"type": {"const": "joint"},
     "joint": {"enum": list(DIRECTIONS)},
     "direction": {"enum": ["increase", "decrease"]},
     "degrees": {"type": "integer", "minimum": 0, "maximum": 20}},
     "required": ["type", "joint", "direction", "degrees"], "additionalProperties": False},
    STEP_SCHEMA["anyOf"][2], STEP_SCHEMA["anyOf"][3]]}
MODEL_PLAN_SCHEMA = {**PLAN_SCHEMA, "properties": {
    **PLAN_SCHEMA["properties"], "steps": {"type": "array", "items": MODEL_STEP_SCHEMA, "maxItems": 12}}}
SYSTEM_PROMPT = """你是机械臂表演导演，只生成JSON计划，绝不直接执行。最多12步。
每一步只允许以下格式：
{"type":"led","value":0到255的整数}；
{"type":"joint","direction":"left/right/up/down/open/close其中之一","degrees":0到20的正角度}；
{"type":"wait","seconds":0到5}；{"type":"greet"}。
水平左/右用direction=left/right，抬头/低头用direction=up/down，夹爪张开/合拢用direction=open/close。
这些方向唯一对应实际关节，不要添加joint字段。
仅明确要求特定关节角度增大/减少时，使用{"type":"joint","joint":"base/shoulder/elbow/gripper其中之一","direction":"increase/decrease其中之一","degrees":0到20}。
不要计算正负号，degrees只能填写正数，实际机械方向由控制器绑定。
格式是{"steps":[...],"explanation":"简短中文说明"}。
只使用已列出的动作。如果要求识别人、抓取未知物品或超出能力，用空steps并说明。
不把未知相机、关节位置或抓取状态当成事实。
例子：向左十度={"type":"joint","direction":"left","degrees":10}；
向右十度={"type":"joint","direction":"right","degrees":10}。
没有指定角度时使用10度，没有指定亮度时亮灯255、关灯0。"""


def _number(value, low, high):
    """Reject bool/NaN as well as values outside the actual action bounds."""
    return (type(value) in (int, float) and math.isfinite(value)
            and low <= value <= high)


def validate_plan(value):
    """Validate independently of the model server's optional JSON grammar."""
    if not isinstance(value, dict) or set(value) != {"steps", "explanation"}:
        raise ValueError("plan must contain exactly steps and explanation")
    if not isinstance(value["explanation"], str) or len(value["explanation"]) > 2000:
        raise ValueError("invalid explanation")
    steps = value["steps"]
    if not isinstance(steps, list) or len(steps) > 12:
        raise ValueError("plan must have at most 12 steps")
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("step must be an object")
        kind = step.get("type")
        if kind == "led":
            valid = (set(step) == {"type", "value"}
                     and type(step["value"]) is int and 0 <= step["value"] <= 255)
        elif kind == "joint":
            valid = (set(step) == {"type", "joint", "delta"}
                     and step["joint"] in ("base", "shoulder", "elbow", "gripper")
                     and _number(step["delta"], -20, 20))
        elif kind == "wait":
            valid = set(step) == {"type", "seconds"} and _number(step["seconds"], 0, 5)
        else:
            valid = kind == "greet" and set(step) == {"type"}
        if not valid:
            raise ValueError("invalid or unsupported step: " + repr(step))
    return value


def compile_model_plan(value):
    """Translate genuine model-selected directions into the public delta schema."""
    if not isinstance(value, dict) or set(value) != {"steps", "explanation"}:
        raise ValueError("invalid model plan")
    if not isinstance(value["steps"], list) or len(value["steps"]) > 12:
        raise ValueError("invalid model step count")
    output = []
    for step in value["steps"]:
        if isinstance(step, dict) and step.get("type") == "joint":
            if set(step) not in ({"type", "direction", "degrees"},
                                  {"type", "joint", "direction", "degrees"}):
                raise ValueError("model joint must use direction and degrees")
            direction = step["direction"]
            if not isinstance(direction, str):
                raise ValueError("model direction must be a string")
            if "joint" not in step:
                joint, sign = SEMANTIC_JOINTS.get(direction, (None, None))
            else:
                joint = step["joint"]
                if not isinstance(joint, str) or direction not in ("increase", "decrease"):
                    raise ValueError("named joints require increase/decrease")
                sign = DIRECTIONS.get(joint, {}).get(direction)
            if sign is None or not _number(step["degrees"], 0, 20):
                raise ValueError("model joint direction or magnitude is invalid: " + repr(step))
            output.append({"type": "joint", "joint": joint,
                           "delta": sign * step["degrees"]})
        else:
            output.append(step)
    return validate_plan({"steps": output, "explanation": value["explanation"]})


def plan(text, url="http://127.0.0.1:8081/v1", model="roarm-director"):
    """Perform real model inference; return validated JSON without sending actions."""
    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
        raise ValueError("director text must be 1..1000 characters")
    endpoint = url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions" if endpoint.endswith("/v1") else "/v1/chat/completions"
    # A small local model needs concrete directional examples in its chat context.
    examples = [("向左转十度", "left"), ("向右转十度", "right"),
                ("张开夹爪十度", "open"), ("合拢夹爪十度", "close")]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for instruction, direction in examples:
        messages.extend([{"role": "user", "content": instruction},
                         {"role": "assistant", "content": json.dumps({
                             "steps": [{"type": "joint", "direction": direction, "degrees": 10}],
                             "explanation": instruction}, ensure_ascii=False)}])
    messages.append({"role": "user", "content": (
        "把以下表演指令转换成计划：" + text + "\n"
        "用方向枚举left/right/up/down/open/close表达原指令，不要计算机械坐标的正负号。只输出JSON。")})
    payload = {"model": model, "temperature": 0, "max_tokens": 700,
               "messages": messages,
               "response_format": {"type": "json_object", "schema": MODEL_PLAN_SCHEMA}}
    request = Request(endpoint, json.dumps(payload).encode(),
                      {"Content-Type": "application/json"}, method="POST")
    # Local/LAN service requests must not be captured by a desktop HTTP proxy.
    with build_opener(ProxyHandler({})).open(request, timeout=90) as response:
        result = json.load(response)
    content = result["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise ValueError("LLM response contains no text")
    return compile_model_plan(json.loads(content))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text")
    parser.add_argument("--url", default="http://127.0.0.1:8081/v1")
    parser.add_argument("--model", default="roarm-director")
    args = parser.parse_args()
    print(json.dumps(plan(args.text, args.url, args.model), ensure_ascii=False, indent=2))
