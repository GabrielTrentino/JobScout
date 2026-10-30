import unittest

from jobscout import places
from jobscout.profile import standard_fields


class PlacesTest(unittest.TestCase):
    def test_language_of_short_questions(self):
        self.assertEqual(places.language("What is your current location?"), "en")
        self.assertEqual(places.language("Country"), "en")
        self.assertEqual(places.language("Qual sua localização atual?"), "pt")
        self.assertEqual(places.language("País"), "pt")
        self.assertEqual(places.language("¿Dónde vives actualmente?"), "es")
        self.assertEqual(places.language("12345"), "pt")

    def test_country_names(self):
        self.assertEqual(places.country("Brasil", "en"), "Brazil")
        self.assertEqual(places.country("brazil", "pt"), "Brasil")
        self.assertEqual(places.country("EUA", "en"), "United States")
        self.assertEqual(places.country("uk", "es"), "Reino Unido")
        self.assertEqual(places.country("Holanda", "es"), "Países Bajos")
        self.assertEqual(places.country("Narnia", "en"), "Narnia")

    def test_location_uses_only_what_is_filled(self):
        self.assertEqual(places.location({"cidade": "Recife", "estado": "PE", "pais": "Brasil"}, "en"), "Recife, PE, Brazil")
        self.assertEqual(places.location({"cidade": "Recife"}, "en"), "Recife")

    def test_standard_fields_carry_language_variants(self):
        fields = {field["chave"]: field for field in standard_fields({"cidade": "Recife", "estado": "PE", "pais": "brasil"})}
        self.assertEqual(fields["pais"]["valor"], "Brasil")
        self.assertEqual(fields["pais"]["valores"]["en"], "Brazil")
        self.assertEqual(fields["localizacao"]["valores"]["en"], "Recife, PE, Brazil")
        self.assertNotIn("valores", fields["cidade"])
        only_city = {field["chave"] for field in standard_fields({"cidade": "Recife"})}
        self.assertEqual(only_city, {"cidade", "localizacao"})


if __name__ == "__main__":
    unittest.main()
