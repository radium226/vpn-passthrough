from typing import Protocol, Self, Callable, AsyncGenerator
from typing import Any, Generator
import os
from multiprocessing import Queue, Process
from dataclasses import dataclass
from contextlib import contextmanager, asynccontextmanager
from loguru import logger
import asyncio
from typing import Type
import inspect


@dataclass
class Invoke():

    method_name: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


@dataclass
class Quit():
    pass


Action = Invoke | Quit


class Service(Protocol):

    async def do_some_stuff(self, foo: str) -> int:
        ...

            


class Worker(Service):

    async def do_some_stuff(self, foo: str) -> int:
        pid = os.getpid()
        print(f"Hello ! {pid=}, {foo=}")
        return 42



class Dispatcher(Service):

    def __init__(self, action_queue: Queue, result_queue: Queue) -> None: # type: ignore[type-arg]
        self._action_queue = action_queue
        self._result_queue = result_queue
    
    async def do_some_stuff(self, foo: str) -> int:
        logger.info("Dispatching! ")
        await asyncio.get_event_loop().run_in_executor(None, self._action_queue.put, Invoke(
            method_name=Worker.do_some_stuff.__name__, 
            args=(foo, ),
            kwargs=dict(),
        ))
        logger.info("Waiting for result... ")
        result = await asyncio.get_event_loop().run_in_executor(None, self._result_queue.get)
        assert isinstance(result, int), "Expected result to be an int"
        return result



@asynccontextmanager
async def create_service() -> AsyncGenerator[Service, None]:
    def process_target(action_queue: Queue, result_queue: Queue) -> None: # type: ignore[type-arg]
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def process_actions() -> None:
            worker = Worker()
            while True:
                try:
                    logger.info("Waiting for action... ")
                    action = await loop.run_in_executor(None, action_queue.get)
                    logger.info("Action received! (action={action})", action=action)

                    match action:
                        case Invoke(method_name, args, kwargs):
                            logger.info("Invoking method... (method_name={method_name})", method_name=method_name)
                            method = getattr(worker, method_name)
                            result = await method(*args, **kwargs)
                            logger.info("Method invoked! (result={result})", result=result)
                            # result = await loop.run_in_executor(None, method, *args, **kwargs)
                            result_queue.put(result)
                            logger.info("Result sent! (result={result})", result=result)

                        case Quit():
                            logger.info("Quitting... ")
                            break
                except asyncio.CancelledError:
                    logger.info("Process cancelled, exiting...")
                    break

        loop.run_until_complete(process_actions())


    action_queue = Queue() # type: ignore[var-annotated]
    result_queue = Queue() # type: ignore[var-annotated]
    process = Process(target=process_target, args=(action_queue, result_queue,))
    process.start()
    logger.info("We are here! ")
    try:
        yield Dispatcher(action_queue, result_queue)
    except Exception as e:
        logger.error("An error occurred: {error}", error=e)
        raise e
    finally:
        logger.info("Cleaning up... ")
        action_queue.put(Quit())
        action_queue.close()
        result_queue.close()
        process.join()



def a(b: int, c: str) -> int:
    print(f"a({b=}, {c=})")
    return b + len(c)


async def main() -> None:
    async with create_service() as service:
        logger.info("Hello ! (service={service})", service=service)
        logger.info("pid={pid}", pid=os.getpid())
        result = await service.do_some_stuff("coucou")
        logger.info("Result: {result}", result=result)





if __name__ == "__main__":
    asyncio.run(main())