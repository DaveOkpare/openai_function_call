from typing import Any, Union, TypeVar, Optional
from collections.abc import Iterable
from pydantic import BaseModel, Field, root_validator
from instructor.process_response import handle_response_model
import instructor
import uuid
import json

T = TypeVar("T", bound=BaseModel)


class Function(BaseModel):
    name: str
    description: str
    parameters: Any


class Tool(BaseModel):
    type: str
    function: Function


class AnthropicTool(BaseModel):
    name: str
    description: str
    input_schema: Any


class RequestBody(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    max_tokens: Optional[int] = Field(default=1000)
    temperature: Optional[float] = Field(default=1.0)
    tools: Optional[list[Union[Tool, AnthropicTool]]] = None
    tool_choice: Optional[dict[str, Any]] = None

    @root_validator(pre=True)
    def map_tools(cls, values):
        tools_data = values.get("tools", [])
        mapped_tools = []
        
        for tool_data in tools_data:
            if "function" in tool_data:
                mapped_tools.append(Tool(**tool_data))
            elif "input_schema" in tool_data:
                mapped_tools.append(AnthropicTool(
                    name=tool_data["name"],
                    description=tool_data["description"],
                    input_schema=tool_data["input_schema"]
                ))
            else:
                raise ValueError("Unknown tool format")
        
        values["tools"] = mapped_tools
        return values


class BatchModel(BaseModel):
    custom_id: str
    params: RequestBody


class BatchJob:
    @classmethod
    def parse_from_file(
        cls, file_path: str, response_model: type[T]
    ) -> tuple[list[T], list[dict[Any, Any]]]:
        with open(file_path) as file:
            res: list[T] = []
            error_objs: list[dict[Any, Any]] = []
            for line in file:
                data = json.loads(line)
                try:
                    if (
                        "tool_calls"
                        in data["response"]["body"]["choices"][0]["message"]
                    ):
                        # OpenAI format
                        res.append(
                            response_model(
                                **json.loads(
                                    data["response"]["body"]["choices"][0]["message"][
                                        "tool_calls"
                                    ][0]["function"]["arguments"]
                                )
                            )
                        )
                    else:
                        # Anthropic format
                        res.append(
                            response_model(
                                **json.loads(
                                    data["result"]["message"]["content"][0]["text"]
                                )
                            )
                        )
                except Exception:
                    error_objs.append(data)

            return res, error_objs

    @classmethod
    def parse_from_string(
        cls, content: str, response_model: type[T]
    ) -> tuple[list[T], list[dict[Any, Any]]]:
        res: list[T] = []
        error_objs: list[dict[Any, Any]] = []
        lines = content.splitlines()
        for line in lines:
            data = json.loads(line)
            try:
                if "tool_calls" in data["response"]["body"]["choices"][0]["message"]:
                    # OpenAI format
                    res.append(
                        response_model(
                            **json.loads(
                                data["response"]["body"]["choices"][0]["message"][
                                    "tool_calls"
                                ][0]["function"]["arguments"]
                            )
                        )
                    )
                else:
                    # Anthropic format
                    res.append(
                        response_model(
                            **json.loads(
                                data["result"]["message"]["content"][0]["text"]
                            )
                        )
                    )
            except Exception:
                error_objs.append(data)

        return res, error_objs

    @classmethod
    def create_from_messages(
        cls,
        messages_batch: Union[
            list[list[dict[str, Any]]], Iterable[list[dict[str, Any]]]
        ],
        model: str,
        response_model: type[BaseModel],
        file_path: str,
        max_tokens: Optional[int] = 1000,
        temperature: Optional[float] = 1.0,
    ):
        use_anthropic = "claude" in model.lower()

        if use_anthropic:
            _, kwargs = handle_response_model(
                response_model=response_model, mode=instructor.Mode.ANTHROPIC_TOOLS
            )
            kwargs.pop("messages")
        else:
            _, kwargs = handle_response_model(
                response_model=response_model, mode=instructor.Mode.TOOLS
            )

        with open(file_path, "w") as file:
            for messages in messages_batch:
                if use_anthropic:
                    batch_model = BatchModel(
                        custom_id=str(uuid.uuid4()),
                        params=RequestBody(
                            model=model,
                            messages=messages,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            **kwargs
                        ),
                    )
                else:
                    batch_model = BatchModel(
                        custom_id=str(uuid.uuid4()),
                        params=RequestBody(
                            model=model,
                            messages=messages,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            **kwargs,
                        ),
                    )
                file.write(batch_model.model_dump_json() + "\n")
