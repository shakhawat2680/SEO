class DataNormalizer:

    def normalize(self, data: dict):

        data["title"] = (data.get("title") or "").strip()
        data["meta_description"] = (data.get("meta_description") or "").strip()

        return data
