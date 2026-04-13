"""Unit tests for the IDS XML parser."""

import pytest

from app.modules.bim_requirements.parsers.ids_parser import IDSParser


@pytest.fixture
def parser() -> IDSParser:
    return IDSParser()


# Minimal valid IDS XML with a single property requirement
MINIMAL_IDS = """\
<?xml version="1.0" encoding="UTF-8"?>
<ids xmlns="http://standards.buildingsmart.org/IDS"
     xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <info>
    <title>Test Requirements</title>
  </info>
  <specifications>
    <specification name="Wall Fire Rating" ifcVersion="IFC4">
      <applicability>
        <entity>
          <name><simpleValue>IFCWALL</simpleValue></name>
        </entity>
      </applicability>
      <requirements>
        <property dataType="IFCLABEL" cardinality="required">
          <propertySet><simpleValue>Pset_WallCommon</simpleValue></propertySet>
          <baseName><simpleValue>FireRating</simpleValue></baseName>
          <value>
            <xs:restriction>
              <xs:enumeration value="REI60"/>
              <xs:enumeration value="REI90"/>
              <xs:enumeration value="REI120"/>
            </xs:restriction>
          </value>
        </property>
      </requirements>
    </specification>
  </specifications>
</ids>
"""

IDS_WITH_PATTERN = """\
<?xml version="1.0" encoding="UTF-8"?>
<ids xmlns="http://standards.buildingsmart.org/IDS"
     xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <specifications>
    <specification name="Space Reference" ifcVersion="IFC4">
      <applicability>
        <entity>
          <name><simpleValue>IFCSPACE</simpleValue></name>
        </entity>
      </applicability>
      <requirements>
        <property dataType="IFCLABEL" cardinality="required">
          <propertySet><simpleValue>Pset_SpaceCommon</simpleValue></propertySet>
          <baseName><simpleValue>Reference</simpleValue></baseName>
          <value>
            <xs:restriction>
              <xs:pattern value="^[A-Z]{{2}}\\d{{3}}$"/>
            </xs:restriction>
          </value>
        </property>
      </requirements>
    </specification>
  </specifications>
</ids>
"""

IDS_WITH_RANGE = """\
<?xml version="1.0" encoding="UTF-8"?>
<ids xmlns="http://standards.buildingsmart.org/IDS"
     xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <specifications>
    <specification name="Thermal" ifcVersion="IFC4">
      <applicability>
        <entity>
          <name><simpleValue>IFCWALL</simpleValue></name>
        </entity>
      </applicability>
      <requirements>
        <property dataType="IFCREAL" cardinality="required">
          <propertySet><simpleValue>Pset_WallCommon</simpleValue></propertySet>
          <baseName><simpleValue>ThermalTransmittance</simpleValue></baseName>
          <value>
            <xs:restriction>
              <xs:minInclusive value="0.1"/>
              <xs:maxInclusive value="1.0"/>
            </xs:restriction>
          </value>
        </property>
      </requirements>
    </specification>
  </specifications>
</ids>
"""

IDS_MULTIPLE_SPECS = """\
<?xml version="1.0" encoding="UTF-8"?>
<ids xmlns="http://standards.buildingsmart.org/IDS"
     xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <specifications>
    <specification name="Wall Reqs" ifcVersion="IFC4">
      <applicability>
        <entity><name><simpleValue>IFCWALL</simpleValue></name></entity>
      </applicability>
      <requirements>
        <property dataType="IFCLABEL" cardinality="required">
          <propertySet><simpleValue>Pset_WallCommon</simpleValue></propertySet>
          <baseName><simpleValue>FireRating</simpleValue></baseName>
        </property>
      </requirements>
    </specification>
    <specification name="Door Reqs" ifcVersion="IFC4">
      <applicability>
        <entity><name><simpleValue>IFCDOOR</simpleValue></name></entity>
      </applicability>
      <requirements>
        <property dataType="IFCBOOLEAN" cardinality="required">
          <propertySet><simpleValue>Pset_DoorCommon</simpleValue></propertySet>
          <baseName><simpleValue>IsExternal</simpleValue></baseName>
        </property>
      </requirements>
    </specification>
  </specifications>
</ids>
"""

IDS_WITH_CLASSIFICATION = """\
<?xml version="1.0" encoding="UTF-8"?>
<ids xmlns="http://standards.buildingsmart.org/IDS"
     xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <specifications>
    <specification name="Classified Wall" ifcVersion="IFC4">
      <applicability>
        <entity><name><simpleValue>IFCWALL</simpleValue></name></entity>
        <classification>
          <system><simpleValue>Uniclass 2015</simpleValue></system>
          <value><simpleValue>EF_25_10</simpleValue></value>
        </classification>
      </applicability>
      <requirements>
        <attribute cardinality="required">
          <name><simpleValue>Name</simpleValue></name>
        </attribute>
      </requirements>
    </specification>
  </specifications>
</ids>
"""

IDS_WITH_ATTRIBUTE = """\
<?xml version="1.0" encoding="UTF-8"?>
<ids xmlns="http://standards.buildingsmart.org/IDS"
     xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <specifications>
    <specification name="Attr Test" ifcVersion="IFC4">
      <applicability>
        <entity>
          <name><simpleValue>IFCWALL</simpleValue></name>
          <predefinedType><simpleValue>SOLIDWALL</simpleValue></predefinedType>
        </entity>
      </applicability>
      <requirements>
        <attribute cardinality="required">
          <name><simpleValue>Description</simpleValue></name>
          <value><simpleValue>External Load-Bearing Wall</simpleValue></value>
        </attribute>
      </requirements>
    </specification>
  </specifications>
</ids>
"""


class TestIDSParser:
    """Tests for the IDS XML parser."""

    def test_simple_property_required(self, parser: IDSParser) -> None:
        """IFCWALL with required FireRating from enum."""
        result = parser.parse(MINIMAL_IDS)
        assert result.success
        assert len(result.requirements) == 1

        req = result.requirements[0]
        assert req.element_filter["ifc_class"] == "IFCWALL"
        assert req.property_group == "Pset_WallCommon"
        assert req.property_name == "FireRating"
        assert req.constraint_def["datatype"] == "IFCLABEL"
        assert req.constraint_def["cardinality"] == "required"
        assert req.constraint_def["enum"] == ["REI60", "REI90", "REI120"]
        assert req.context["ifc_version"] == "IFC4"
        assert req.context["use_case"] == "Wall Fire Rating"

    def test_property_with_pattern(self, parser: IDSParser) -> None:
        """Property with regex pattern constraint."""
        result = parser.parse(IDS_WITH_PATTERN)
        assert result.success
        assert len(result.requirements) == 1

        req = result.requirements[0]
        assert req.property_name == "Reference"
        assert "pattern" in req.constraint_def

    def test_property_with_numeric_range(self, parser: IDSParser) -> None:
        """Numeric property with min/max range."""
        result = parser.parse(IDS_WITH_RANGE)
        assert result.success
        req = result.requirements[0]
        assert req.constraint_def["min"] == 0.1
        assert req.constraint_def["max"] == 1.0
        assert req.constraint_def["datatype"] == "IFCREAL"

    def test_multiple_specifications(self, parser: IDSParser) -> None:
        """File with multiple specifications produces multiple requirements."""
        result = parser.parse(IDS_MULTIPLE_SPECS)
        assert result.success
        assert len(result.requirements) == 2

        ifc_classes = {r.element_filter["ifc_class"] for r in result.requirements}
        assert ifc_classes == {"IFCWALL", "IFCDOOR"}

    def test_classification_filter(self, parser: IDSParser) -> None:
        """Applicability with classification system."""
        result = parser.parse(IDS_WITH_CLASSIFICATION)
        assert result.success
        req = result.requirements[0]
        assert req.element_filter["classification"]["system"] == "Uniclass 2015"
        assert req.element_filter["classification"]["value"] == "EF_25_10"

    def test_combined_applicability(self, parser: IDSParser) -> None:
        """IFC class + predefined type in applicability."""
        result = parser.parse(IDS_WITH_ATTRIBUTE)
        assert result.success
        req = result.requirements[0]
        assert req.element_filter["ifc_class"] == "IFCWALL"
        assert req.element_filter["predefined_type"] == "SOLIDWALL"
        assert req.property_group is None  # attribute, not property
        assert req.property_name == "Description"
        assert req.constraint_def["value"] == "External Load-Bearing Wall"

    def test_invalid_xml(self, parser: IDSParser) -> None:
        """Invalid XML produces errors, not exceptions."""
        result = parser.parse("this is not XML at all <<>>")
        assert not result.success
        assert result.has_errors
        assert any("Invalid XML" in e["msg"] for e in result.errors)

    def test_empty_specifications(self, parser: IDSParser) -> None:
        """File with no specifications produces a warning."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<ids xmlns="http://standards.buildingsmart.org/IDS">
  <specifications>
  </specifications>
</ids>
"""
        result = parser.parse(xml)
        assert not result.success
        assert len(result.warnings) > 0

    def test_metadata_extraction(self, parser: IDSParser) -> None:
        """Parser extracts metadata from the IDS file."""
        result = parser.parse(MINIMAL_IDS)
        assert result.metadata.get("title") == "Test Requirements"
        assert result.metadata.get("specification_count") == 1
