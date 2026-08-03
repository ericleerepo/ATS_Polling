from jobradar import filters
from jobradar.model import Posting


def posting(title="Software Engineer", location="San Francisco", description="", **kw):
    return Posting(
        source="greenhouse",
        company="Acme",
        external_id="1",
        url="",
        title=title,
        location=location,
        description=description,
        **kw,
    )


# --- role family ---

def test_role_keeps():
    for title, bucket in [
        ("Machine Learning Engineer", "ml_ai"),
        ("ML Engineer, Infrastructure", "ml_ai"),
        ("AI Engineer", "ml_ai"),
        ("Applied Scientist", "ml_ai"),
        ("Software Engineer, Backend", "swe"),
        ("Full Stack Developer", "swe"),
        ("Frontend Engineer", "swe"),
        ("Forward Deployed Engineer", "fde"),
        ("Solutions Architect", "fde"),
        ("Deployment Strategist", "fde"),
    ]:
        r = filters.apply(posting(title=title))
        assert r.kept and r.bucket == bucket, title


def test_role_drops():
    for title in [
        "Product Manager",
        "Account Executive",
        "Recruiter",
        "Product Designer",
        "Data Analyst",
        "Sales Development Representative",
    ]:
        r = filters.apply(posting(title=title))
        assert not r.kept, title
        assert r.reason in ("role", "seniority:title"), title


def test_hybrid_carveout_kept_and_flagged():
    r = filters.apply(posting(title="Data Scientist"))
    assert r.kept and r.hybrid_flag and r.bucket == "hybrid"
    r = filters.apply(posting(title="Machine Learning Researcher"))
    assert r.kept and r.hybrid_flag


# --- seniority ---

def test_seniority_title_drops():
    for title in [
        "Staff Software Engineer",
        "Principal Solutions Architect",
        "Engineering Manager, Backend",
        "Tech Lead, Frontend",
    ]:
        r = filters.apply(posting(title=title))
        assert not r.kept and r.reason == "seniority:title", title


def test_technical_account_manager_exempt_from_manager_drop():
    r = filters.apply(posting(title="Technical Account Manager"))
    assert r.kept and r.bucket == "fde"


def test_senior_kept_but_flagged():
    r = filters.apply(posting(title="Senior Software Engineer"))
    assert r.kept and r.senior_flag


def test_leadership_in_description_does_not_drop():
    r = filters.apply(
        posting(description="You will lead projects and mentor. Leadership skills valued.")
    )
    assert r.kept


def test_years_requirement():
    assert filters.requires_7plus_years("7+ years of experience required")
    assert filters.requires_7plus_years("requires 10+ years in backend")
    assert filters.requires_7plus_years("at least 8 years of experience")
    assert not filters.requires_7plus_years("3-7 years of experience")
    assert not filters.requires_7plus_years("5 - 10 years of experience")
    assert not filters.requires_7plus_years("2+ years of experience")
    r = filters.apply(posting(description="You need 9+ years of Kubernetes."))
    assert not r.kept and r.reason == "seniority:years"


# --- location ---

def test_location_keeps():
    for loc in [
        "San Francisco",
        "San Francisco, CA",
        "SF Bay Area",
        "Mountain View; New York",  # any-location-passes
        "Remote (United States)",
        "Remote - US",
        "Remote",  # bare remote: ambiguous, keep
        "",  # no data: ambiguous, keep
    ]:
        r = filters.apply(posting(location=loc))
        assert r.kept, repr(loc)


def test_location_drops():
    for loc in [
        "New York",
        "Seattle, WA",
        "London, United Kingdom",
        "Remote - Europe",
        "Remote (UK)",
        "Bangalore, India",
        "Toronto, Canada",
    ]:
        r = filters.apply(posting(location=loc))
        assert not r.kept and r.reason == "location", loc


def test_location_uses_structured_country():
    # Lever gives country codes; remote in GB is not remote-US.
    r = filters.apply(posting(location="Remote", workplace_type="remote", country="GB"))
    assert not r.kept
    r = filters.apply(posting(location="Remote", workplace_type="remote", country="US"))
    assert r.kept
