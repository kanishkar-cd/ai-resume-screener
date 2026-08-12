import pytest
from app.services.scoring.component_scoring_service import ComponentScoringService


@pytest.mark.parametrize(
    "degree_str,expected_rank",
    [
        ("B.Sc", 3),
        ("B.Sc in Computer Science", 3),
        ("B.Com", 3),
        ("BCA", 3),
        ("B.Tech", 3),
        ("B.E", 3),
        ("Bachelor of Engineering", 3),
        ("Bachelor of Science", 3),
        ("M.Sc", 4),
        ("M.Sc in Data Science", 4),
        ("MCA", 4),
        ("MBA", 4),
        ("Master of Science", 4),
        ("Master of Business Administration", 4),
        ("PhD", 5),
        ("Doctor of Philosophy", 5),
        ("High School", 1),
        (None, 0),
        ("Random Unrecognized Degree", 0),
    ],
)
def test_degree_alias_ranks(degree_str: str | None, expected_rank: int):
    assert ComponentScoringService.degree_rank(degree_str) == expected_rank
