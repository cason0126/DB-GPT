from abc import ABC, abstractmethod, ABCMeta

from types import FunctionType
from typing import (
    List,
    Generic,
    TypeVar,
    AsyncIterator,
    Union,
    Any,
    Dict,
    Optional,
    cast,
)
import functools
from inspect import signature

from ..dag.base import DAGNode, DAGContext, DAGVar, DAG
from ..task.base import (
    TaskContext,
    TaskOutput,
    TaskState,
    OUT,
    T,
    InputContext,
    InputSource,
)

F = TypeVar("F", bound=FunctionType)

CALL_DATA = Union[Dict, Dict[str, Dict]]


class WorkflowRunner(ABC, Generic[T]):
    """Abstract base class representing a runner for executing workflows in a DAG.

    This class defines the interface for executing workflows within the DAG,
    handling the flow from one DAG node to another.
    """

    @abstractmethod
    async def execute_workflow(
        self, node: "BaseOperator", call_data: Optional[CALL_DATA] = None
    ) -> DAGContext:
        """Execute the workflow starting from a given operator.

        Args:
            node (RunnableDAGNode): The starting node of the workflow to be executed.
            call_data (CALL_DATA): The data pass to root operator node.

        Returns:
            DAGContext: The context after executing the workflow, containing the final state and data.
        """


default_runner: WorkflowRunner = None


class BaseOperatorMeta(ABCMeta):
    """Metaclass of BaseOperator."""

    @classmethod
    def _apply_defaults(cls, func: F) -> F:
        sig_cache = signature(func)

        @functools.wraps(func)
        def apply_defaults(self: "BaseOperator", *args: Any, **kwargs: Any) -> Any:
            dag: Optional[DAG] = kwargs.get("dag") or DAGVar.get_current_dag()
            task_id: Optional[str] = kwargs.get("task_id")
            if not task_id and dag:
                task_id = dag._new_node_id()
            runner: Optional[WorkflowRunner] = kwargs.get("runner") or default_runner
            # print(f"self: {self}, kwargs dag: {kwargs.get('dag')}, kwargs: {kwargs}")
            # for arg in sig_cache.parameters:
            #     if arg not in kwargs:
            #         kwargs[arg] = default_args[arg]
            if not kwargs.get("dag"):
                kwargs["dag"] = dag
            if not kwargs.get("task_id"):
                kwargs["task_id"] = task_id
            if not kwargs.get("runner"):
                kwargs["runner"] = runner
            real_obj = func(self, *args, **kwargs)
            return real_obj

        return cast(T, apply_defaults)

    def __new__(cls, name, bases, namespace, **kwargs):
        new_cls = super().__new__(cls, name, bases, namespace, **kwargs)
        new_cls.__init__ = cls._apply_defaults(new_cls.__init__)
        return new_cls


class BaseOperator(DAGNode, ABC, Generic[OUT], metaclass=BaseOperatorMeta):
    """Abstract base class for operator nodes that can be executed within a workflow.

    This class extends DAGNode by adding execution capabilities.
    """

    def __init__(
        self,
        task_id: Optional[str] = None,
        task_name: Optional[str] = None,
        dag: Optional[DAG] = None,
        runner: WorkflowRunner = None,
        **kwargs,
    ) -> None:
        """Initializes a BaseOperator with an optional workflow runner.

        Args:
            runner (WorkflowRunner, optional): The runner used to execute the workflow. Defaults to None.
        """
        super().__init__(node_id=task_id, node_name=task_name, dag=dag, **kwargs)
        if not runner:
            from pilot.awel import DefaultWorkflowRunner

            runner = DefaultWorkflowRunner()

        self._runner: WorkflowRunner = runner
        self._dag_ctx: DAGContext = None

    @property
    def current_dag_context(self) -> DAGContext:
        return self._dag_ctx

    async def _run(self, dag_ctx: DAGContext) -> TaskOutput[OUT]:
        if not self.node_id:
            raise ValueError(f"The DAG Node ID can't be empty, current node {self}")
        self._dag_ctx = dag_ctx
        return await self._do_run(dag_ctx)

    @abstractmethod
    async def _do_run(self, dag_ctx: DAGContext) -> TaskOutput[OUT]:
        """
        Abstract method to run the task within the DAG node.

        Args:
            dag_ctx (DAGContext): The context of the DAG when this node is run.

        Returns:
            TaskOutput[OUT]: The task output after this node has been run.
        """

    async def call(self, call_data: Optional[CALL_DATA] = None) -> OUT:
        """Execute the node and return the output.

        This method is a high-level wrapper for executing the node.

        Args:
            call_data (CALL_DATA): The data pass to root operator node.

        Returns:
            OUT: The output of the node after execution.
        """
        out_ctx = await self._runner.execute_workflow(self, call_data)
        return out_ctx.current_task_context.task_output.output

    async def call_stream(
        self, call_data: Optional[CALL_DATA] = None
    ) -> AsyncIterator[OUT]:
        """Execute the node and return the output as a stream.

        This method is used for nodes where the output is a stream.

        Args:
            call_data (CALL_DATA): The data pass to root operator node.

        Returns:
            AsyncIterator[OUT]: An asynchronous iterator over the output stream.
        """
        out_ctx = await self._runner.execute_workflow(self, call_data)
        return out_ctx.current_task_context.task_output.output_stream


def initialize_awel(runner: WorkflowRunner):
    global default_runner
    default_runner = runner
