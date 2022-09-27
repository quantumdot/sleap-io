"""Data structures for data associated with a single instance such as an animal.

The `Instance` class is a SLEAP data structure that contains a collection of `Point`s
that correspond to landmarks within a `Skeleton`.

`PredictedInstance` additionally contains metadata associated with how the instance was
estimated, such as confidence scores.
"""

from __future__ import annotations
from attrs import define, validators, field, cmp_using
from typing import Optional, Union
from sleap_io import Skeleton, Node
import numpy as np
import math

def _point_comparison(a, b) -> bool:
    return bool(np.isclose(a, b, equal_nan=True))

@define
class Point:
    """A 2D spatial landmark and metadata associated with annotation.

    Attributes:
        x: The horizontal pixel location of point in image coordinates.
        y: The vertical pixel location of point in image coordinates.
        visible: Whether point is visible in the image or not.
        complete: Has the point been verified by the user labeler.
    """

    x: float = field(eq=cmp_using(eq=_point_comparison)) # type: ignore
    y: float = field(eq=cmp_using(eq=_point_comparison)) # type: ignore
    visible: bool = True
    complete: bool = False

    def numpy(self) -> np.ndarray:
        """Return the coordinates as a numpy array of shape `(2,)`."""
        return np.array([self.x, self.y]) if self.visible else np.full((2,), np.nan)


@define
class PredictedPoint(Point):
    """A predicted point with associated score generated by a prediction model.

    It has all the properties of a labeled `Point`, plus a `score`.

    Attributes:
        x: The horizontal pixel location of point within image frame.
        y: The vertical pixel location of point within image frame.
        visible: Whether point is visible in the image or not.
        complete: Has the point been verified by the user labeler.
        score: The point-level prediction score. This is typically the confidence and
            set to a value between 0 and 1.
    """

    score: float = 0.0

    def numpy(self) -> np.ndarray:
        """Return the coordinates and score as a numpy array of shape `(3,)`."""
        return (
            np.array([self.x, self.y, self.score])
            if self.visible
            else np.full((3,), np.nan)
        )


@define(eq=False)
class Track:
    """An object that represents the same animal/object across multiple detections.

    This allows tracking of unique entities in the video over time and space.

    A `Track` may also be used to refer to unique identity classes that span multiple
    videos, such as `"female mouse"`.

    Attributes:
        name: A name given to this track for identification purposes.

    Notes:
        `Track`s are compared by identity. This means that unique track objects with the
        same name are considered to be different.
    """

    name: str = ""


def compare_points(
    a: Union[dict[Node, Point], dict[Node, PredictedPoint]],
    b: Union[dict[Node, Point], dict[Node, PredictedPoint]],
) -> bool:
    """Compare this instances points to another set of points"""
    # First check we are speaking the same languague of nodes
    if not set(a.keys()) == set(b.keys()):
        return False

    # check each point in self vs other
    for node, point in a.items():
        if not point == b[node]:
            print(node.name)
            return False

    # otherwise, return True
    return True


@define(auto_attribs=True, slots=True, eq=True)
class Instance:
    """This class represents a ground truth instance such as an animal.

    An `Instance` has a set of landmarks (`Point`s) that correspond to the nodes defined
    in its `Skeleton`.

    It may also be associated with a `Track` which links multiple instances together
    across frames or videos.

    Attributes:
        points: A dictionary with keys as `Node`s and values as `Point`s containing all
            of the landmarks of the instance. This can also be specified as a dictionary
            with node names, a list of length `n_nodes`, or a numpy array of shape
            `(n_nodes, 2)`.
        skeleton: The `Skeleton` that describes the `Node`s and `Edge`s associated with
            this instance.
        track: An optional `Track` associated with a unique animal/object across frames
            or videos.
        from_predicted: The `PredictedInstance` (if any) that this instance was
            initialized from. This is used with human-in-the-loop workflows.
    """

    _POINT_TYPE = Point

    def _make_default_point(self, x, y):
        return self._POINT_TYPE(x, y, visible=not (math.isnan(x) or math.isnan(y)))

    def _convert_points(self, attr, points):
        """Callback for maintaining points mappings between nodes and points."""
        if type(points) == np.ndarray:
            points = points.tolist()

        if type(points) == list:
            if len(points) != len(self.skeleton):
                raise ValueError(
                    "If specifying points as a list, must provide as many points as "
                    "nodes in the skeleton."
                )
            points = {node: pt for node, pt in zip(self.skeleton.nodes, points)}

        if type(points) == dict:
            keys = [
                node if type(node) == Node else self.skeleton[node]
                for node in points.keys()
            ]
            vals = [
                point
                if type(point) == self._POINT_TYPE
                else self._make_default_point(*point)
                for point in points.values()
            ]
            points = {k: v for k, v in zip(keys, vals)}

        missing_nodes = list(set(self.skeleton.nodes) - set(points.keys()))
        for node in missing_nodes:
            points[node] = self._make_default_point(x=np.nan, y=np.nan)

        return points

    points: Union[dict[Node, Point], dict[Node, PredictedPoint]] = field(
        on_setattr=_convert_points, eq=cmp_using(eq=compare_points) # type: ignore
    )
    skeleton: Skeleton
    track: Optional[Track] = None
    from_predicted: Optional[PredictedInstance] = None

    def __attrs_post_init__(self):
        """Maintain point mappings between node and points after initialization."""
        super().__setattr__("points", self._convert_points(None, self.points))

    def __getitem__(self, node: Union[int, str, Node]) -> Optional[Point]:
        """Return the point associated with a node or `None` if not set."""
        if (type(node) == int) or (type(node) == str):
            node = self.skeleton[node]
        if isinstance(node, Node):
            return self.points.get(node, None)
        else:
            raise IndexError(f"Invalid indexing argument for instance: {node}")

    def __len__(self) -> int:
        """Return the number of points in the instance."""
        return len(self.points)

    @property
    def n_visible(self) -> int:
        """Return the number of visible points in the instance."""
        return sum(pt.visible for pt in self.points.values())

    @property
    def is_empty(self) -> bool:
        """Return `True` if no points are visible on the instance."""
        return self.n_visible == 0

    @classmethod
    def from_numpy(
        cls, points: np.ndarray, skeleton: Skeleton, track: Optional[Track] = None
    ) -> "Instance":
        """Create an instance object from a numpy array.

        Args:
            points: A numpy array of shape `(n_nodes, 2)` corresponding to the points of
                the skeleton. Values of `np.nan` indicate "missing" nodes.
            skeleton: The `Skeleton` that this `Instance` is associated with. It should
                have `n_nodes` nodes.
            track: An optional `Track` associated with a unique animal/object across
                frames or videos.
        """
        return cls(
            points=points, skeleton=skeleton, track=track  # type: ignore[arg-type]
        )

    def numpy(self) -> np.ndarray:
        """Return the instance points as a numpy array."""
        pts = np.full((len(self.skeleton), 2), np.nan)
        for node, point in self.points.items():
            if point.visible:
                pts[self.skeleton.index(node)] = point.numpy()
        return pts


@define
class PredictedInstance(Instance):
    """A `PredictedInstance` is an `Instance` that was predicted using a model.

    Args:
        skeleton: The `Skeleton` that this `Instance` is associated with.
        points: A dictionary where keys are `Skeleton` nodes and values are `Point`s.
        track: An optional `Track` associated with a unique animal/object across frames
            or videos.
        from_predicted: Not applicable in `PredictedInstance`s (must be set to `None`).
        score: The instance detection or part grouping prediction score. This is a
            scalar that represents the confidence with which this entire instance was
            predicted. This may not always be applicable depending on the model type.
        tracking_score: The score associated with the `Track` assignment. This is
            typically the value from the score matrix used in an identity assignment.
    """

    _POINT_TYPE = PredictedPoint

    from_predicted: Optional[PredictedInstance] = field(
        default=None, validator=validators.instance_of(type(None))
    )
    score: float = 0.0
    tracking_score: Optional[float] = 0

    @classmethod
    def from_numpy(  # type: ignore[override]
        cls,
        points: np.ndarray,
        point_scores: np.ndarray,
        instance_score: float,
        skeleton: Skeleton,
        tracking_score: Optional[float] = None,
        track: Optional[Track] = None,
    ) -> "PredictedInstance":
        """Create an instance object from a numpy array.

        Args:
            points: A numpy array of shape `(n_nodes, 2)` corresponding to the points of
                the skeleton. Values of `np.nan` indicate "missing" nodes.
            point_scores: The points-level prediction score. This is an array that
                represents the confidence with which each point in the instance was
                predicted. This may not always be applicable depending on the model
                type.
            instance_score: The instance detection or part grouping prediction score.
                This is a scalar that represents the confidence with which this entire
                instance was predicted. This may not always be applicable depending on
                the model type.
            skeleton: The `Skeleton` that this `Instance` is associated with. It should
                have `n_nodes` nodes.
            tracking_score: The score associated with the `Track` assignment. This is
                typically the value from the score matrix used in an identity
                assignment.
            track: An optional `Track` associated with a unique animal/object across
                frames or videos.
        """
        node_points = {
            node: PredictedPoint(pt[0], pt[1], score=score)
            for node, pt, score in zip(skeleton.nodes, points, point_scores)
        }
        return cls(
            points=node_points,
            skeleton=skeleton,
            score=instance_score,
            tracking_score=tracking_score,
            track=track,
        )

    def numpy(self) -> np.ndarray:
        """Return the instance points as a numpy array."""
        pts = np.full((len(self.skeleton), 3), np.nan)
        for node, point in self.points.items():
            if point.visible:
                pts[self.skeleton.index(node)] = point.numpy()
        return pts
