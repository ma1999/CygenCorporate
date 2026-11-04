from app.core.base_plugin import BasePlugin


class Plugin(BasePlugin):
    name = "sample_hello"

    def register(self):
        from flask import jsonify

        def hello():
            return jsonify({"plugin": self.name, "message": "hello from plugin"})

        # avoid duplicate endpoint on re-register
        if "plugins.hello" not in dict(self.app.view_functions):
            bp = __import__("flask").Blueprint(
                f"plugin_{self.name}", __name__
            )
            bp.add_url_rule("/api/plugins/hello", "hello", hello)
            self.app.register_blueprint(bp)
