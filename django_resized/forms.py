import sys
from io import BytesIO
from PIL import Image, ImageFile, ImageOps, ExifTags
from django.conf import settings
from django.core.files.base import ContentFile

try:
    from sorl.thumbnail import ImageField
except ImportError:
    from django.db.models import ImageField


DEFAULT_SIZE = getattr(settings, 'DJANGORESIZED_DEFAULT_SIZE', [1920, 1080])
DEFAULT_QUALITY = getattr(settings, 'DJANGORESIZED_DEFAULT_QUALITY', -1)
DEFAULT_KEEP_META = getattr(settings, 'DJANGORESIZED_DEFAULT_KEEP_META', True)
DEFAULT_FORCE_FORMAT = getattr(settings, 'DJANGORESIZED_DEFAULT_FORCE_FORMAT', None)
DEFAULT_FORMAT_EXTENSIONS = getattr(settings, 'DJANGORESIZED_DEFAULT_FORMAT_EXTENSIONS', {})
DEFAULT_NORMALIZE_ROTATION = getattr(settings, 'DJANGORESIZED_DEFAULT_NORMALIZE_ROTATION', True)


def normalize_rotation(image):
    """
    Find orientation header and rotate the actual data instead.
    Adapted from http://stackoverflow.com/a/6218425/723090
    """
    try:
        image._getexif()
    except AttributeError:
        """ No exit data; this image is not a jpg and can be skipped. """
        return image

    for orientation in ExifTags.TAGS.keys():
        """ Look for orientation header, stop when found. """
        if ExifTags.TAGS[orientation] == 'Orientation':
            break
    else:
        """ No orientation header found, do nothing. """
        return image
    """ Apply the different possible orientations to the data; preserve format. """
    format = image.format
    exif = image._getexif()
    if exif is None:
        return image
    action_nr = exif.get(orientation, None)
    if action_nr is None:
        """ Empty orientation exif data """
        return image
    if action_nr in (3, 4):
        image = image.rotate(180, expand=True)
    elif action_nr in (5, 6):
        image = image.rotate(270, expand=True)
    elif action_nr in (7, 8):
        image = image.rotate(90, expand=True)
    if action_nr in (2, 4, 5, 7):
        image = ImageOps.mirror(image)
    image.format = format
    return image


class ResizedImageFieldFile(ImageField.attr_class):

    def save(self, name, content, save=True):
        content.file.seek(0)
        img = Image.open(content.file)

        if DEFAULT_NORMALIZE_ROTATION:
            img = normalize_rotation(img)

        rgb_formats = ('jpeg', 'jpg', 'png')
        if self.field.force_format and self.field.force_format.lower() in rgb_formats and img.mode != 'RGB':
            img = img.convert('RGB')

        if self.field.crop:
            thumb = ImageOps.fit(
                img,
                self.field.size,
                Image.ANTIALIAS,
                centering=self.get_centring()
            )
        else:
            img.thumbnail(
                self.field.size,
                Image.ANTIALIAS,
            )
            thumb = img

        img_info = img.info
        if not self.field.keep_meta:
            img_info.pop('exif', None)

        ImageFile.MAXBLOCK = max(ImageFile.MAXBLOCK, thumb.size[0] * thumb.size[1])
        new_content = BytesIO()
        img_format = img.format if self.field.force_format is None else self.field.force_format
        thumb.save(new_content, format=img_format, quality=self.field.quality, **img_info)
        new_content = ContentFile(new_content.getvalue())

        name = self.get_name(name, img_format)
        super(ResizedImageFieldFile, self).save(name, new_content, save)

    def get_name(self, name, format):
        extensions = Image.registered_extensions()
        extensions = {v: k for k, v in extensions.items()}
        extensions.update({
            "PNG": ".png",  # It uses .apng otherwise
        })
        extensions.update(DEFAULT_FORMAT_EXTENSIONS)
        if format in extensions:
            name = name.rsplit('.', 1)[0] + extensions[format]
        return name

    def get_centring(self):
        vertical = {
            'top': 0,
            'middle': 0.5,
            'bottom': 1,
        }
        horizontal = {
            'left': 0,
            'center': 0.5,
            'right': 1,
        }
        return [
            vertical[self.field.crop[0]],
            horizontal[self.field.crop[1]],
        ]


class ResizedImageField(ImageField):

    attr_class = ResizedImageFieldFile

    def __init__(self, verbose_name=None, name=None, **kwargs):
        # migrate from 0.2.x
        depricated = ('max_width', 'max_height', 'use_thumbnail_aspect_ratio', 'background_color')
        for argname in depricated:
            if argname in kwargs:
                sys.stderr.write('Error: Keyword argument %s is deprecated for ResizedImageField, see README https://github.com/un1t/django-resized\n' % argname)
                del kwargs[argname]

        self.size = kwargs.pop('size', DEFAULT_SIZE)
        self.crop = kwargs.pop('crop', None)
        self.quality = kwargs.pop('quality', DEFAULT_QUALITY)
        self.keep_meta = kwargs.pop('keep_meta', DEFAULT_KEEP_META)
        self.force_format = kwargs.pop('force_format', DEFAULT_FORCE_FORMAT)
        super(ResizedImageField, self).__init__(verbose_name, name, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super(ImageField, self).deconstruct()
        for custom_kwargs in ['crop', 'size', 'quality', 'keep_meta', 'force_format']:
            kwargs[custom_kwargs] = getattr(self, custom_kwargs)
        return name, path, args, kwargs
