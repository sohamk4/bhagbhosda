from .events import EventsService
from .exchange_rates import ExchangeRateService
from .images import ImagesService
from .messages import MessagesService
from .payment_options import PaymentOptionsService
from .profile import ProfileService
from .requests import RequestService
from .vision import VisionService
from .event_enrichment import EventEnrichmentService

class ServiceContainer:

    def __init__(self, connection):
        self.connection = connection

        self.profile = ProfileService(
            connection
        )

        self.requests = RequestService(
            connection
        )

        self.events = EventsService(
            connection
        )

        self.messages = MessagesService(
            connection
        )

        self.images = ImagesService(
            connection
        )

        self.payment_options = PaymentOptionsService(
            connection
        )

        self.exchange_rates = ExchangeRateService(
            connection
        )

        self.vision = VisionService()

        self.event_enrichment = EventEnrichmentService(
            self
        )
    def extract_image_context(
        self,
        user_id: str,
        request_id: str | None = None,
        related_event_id: str | None = None,
    ) -> list[dict]:
    
        images = self.images.get_images(
            user_id=user_id,
            request_id=request_id,
            related_event_id=related_event_id,
        )
    
        results = []
    
        for image in images:
    
            image_path = self.images.get_image_path(
                image["image_id"]
            )
    
            if not image_path:
                continue
    
            extracted = self.vision.extract_financial_facts(
                image_path=image_path,
                image_id=image["image_id"],
                related_event_id=image["related_event_id"],
            )
    
            results.append(extracted)
    
        return results