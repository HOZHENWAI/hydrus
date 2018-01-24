import bs4
import ClientNetworking
import collections
import HydrusConstants as HC
import HydrusData
import HydrusExceptions
import HydrusGlobals as HG
import HydrusSerialisable
import HydrusTags
import os
import re
import time
import urlparse

def ConvertContentResultToPrettyString( result ):
    
    ( ( name, content_type, additional_info ), parsed_text ) = result
    
    if content_type == HC.CONTENT_TYPE_URLS:
        
        return 'url: ' + parsed_text
        
    elif content_type == HC.CONTENT_TYPE_MAPPINGS:
        
        return 'tag: ' + HydrusTags.CombineTag( additional_info, parsed_text )
        
    elif content_type == HC.CONTENT_TYPE_VETO:
        
        return 'veto'
        
    
    raise NotImplementedError()
    
def ConvertParsableContentToPrettyString( parsable_content, include_veto = False ):
    
    pretty_strings = []
    
    content_type_to_additional_infos = HydrusData.BuildKeyToSetDict( ( ( content_type, additional_infos ) for ( name, content_type, additional_infos ) in parsable_content ) )
    
    for ( content_type, additional_infos ) in content_type_to_additional_infos.items():
        
        if content_type == HC.CONTENT_TYPE_URLS:
            
            pretty_strings.append( 'urls' )
            
        elif content_type == HC.CONTENT_TYPE_MAPPINGS:
            
            namespaces = [ namespace for namespace in additional_infos if namespace != '' ]
            
            if '' in additional_infos:
                
                namespaces.append( 'unnamespaced' )
                
            
            pretty_strings.append( 'tags: ' + ', '.join( namespaces ) )
            
        elif content_type == HC.CONTENT_TYPE_VETO:
            
            if include_veto:
                
                pretty_strings.append( 'veto' )
                
            
        
    
    if len( pretty_strings ) == 0:
        
        return 'nothing'
        
    else:
        
        return ', '.join( pretty_strings )
        
    
def GetChildrenContent( job_key, children, data, referral_url ):
    
    content = []
    
    for child in children:
        
        try:
            
            if isinstance( child, ParseNodeContentLink ):
                
                child_content = child.Parse( job_key, data, referral_url )
                
            elif isinstance( child, ContentParser ):
                
                child_content = child.Parse( data )
                
            
        except HydrusExceptions.VetoException:
            
            return []
            
        
        content.extend( child_content )
        
    
    return content
    
def GetTagsFromContentResults( results ):
    
    tag_results = []
    
    for ( ( name, content_type, additional_info ), parsed_text ) in results:
        
        if content_type == HC.CONTENT_TYPE_MAPPINGS:
            
            tag_results.append( HydrusTags.CombineTag( additional_info, parsed_text ) )
            
        
    
    tag_results = HydrusTags.CleanTags( tag_results )
    
    return tag_results
    
def GetURLsFromContentResults( results ):
    
    url_results = collections.defaultdict( list )
    
    for ( ( name, content_type, additional_info ), parsed_text ) in results:
        
        if content_type == HC.CONTENT_TYPE_URLS:
            
            priority = additional_info
            
            if priority is None:
                
                priority = -1
                
            
            url_results[ priority ].append( parsed_text )
            
        
    
    # ( priority, url_list ) pairs
    
    url_results = list( url_results.items() )
    
    # ordered by descending priority
    
    url_results.sort( reverse = True )
    
    # url_lists of descending priority
    
    url_results = [ url_list for ( priority, url_list ) in url_results ]
    
    return url_results
    
def RenderTagRule( ( name, attrs, index ) ):
    
    if index is None:
        
        result = 'all ' + name + ' tags'
        
    else:
        
        result = HydrusData.ConvertIntToFirst( index + 1 ) + ' ' + name + ' tag'
        
    
    if len( attrs ) > 0:
        
        result += ' with ' + ' and '.join( [ key + ' = ' + value for ( key, value ) in attrs.items() ] )
        
    
    return result
    
HTML_CONTENT_ATTRIBUTE = 0
HTML_CONTENT_STRING = 1
HTML_CONTENT_HTML = 2

class ParseFormulaHTML( HydrusSerialisable.SerialisableBase ):
    
    SERIALISABLE_TYPE = HydrusSerialisable.SERIALISABLE_TYPE_PARSE_FORMULA_HTML
    SERIALISABLE_NAME = 'HTML Parsing Formula'
    SERIALISABLE_VERSION = 5
    
    def __init__( self, tag_rules = None, content_to_fetch = None, attribute_to_fetch = None, string_match = None, string_converter = None ):
        
        if tag_rules is None:
            
            tag_rules = [ ( 'a', {}, None ) ]
            
        
        if content_to_fetch is None:
            
            content_to_fetch = HTML_CONTENT_ATTRIBUTE
            
        
        if attribute_to_fetch is None:
            
            attribute_to_fetch = 'href'
            
        
        if string_match is None:
            
            string_match = StringMatch()
            
        
        if string_converter is None:
            
            string_converter = StringConverter( example_string = 'parsed information' )
            
        
        self._tag_rules = tag_rules
        
        self._content_to_fetch = content_to_fetch
        
        self._attribute_to_fetch = attribute_to_fetch
        
        self._string_match = string_match
        self._string_converter = string_converter
        
    
    def _GetSerialisableInfo( self ):
        
        serialisable_string_match = self._string_match.GetSerialisableTuple()
        serialisable_string_converter = self._string_converter.GetSerialisableTuple()
        
        return ( self._tag_rules, self._content_to_fetch, self._attribute_to_fetch, serialisable_string_match, serialisable_string_converter )
        
    
    def _InitialiseFromSerialisableInfo( self, serialisable_info ):
        
        ( self._tag_rules, self._content_to_fetch, self._attribute_to_fetch, serialisable_string_match, serialisable_string_converter ) = serialisable_info
        
        self._string_match = HydrusSerialisable.CreateFromSerialisableTuple( serialisable_string_match )
        self._string_converter = HydrusSerialisable.CreateFromSerialisableTuple( serialisable_string_converter )
        
    
    def _ParseContent( self, root ):
        
        if self._content_to_fetch == HTML_CONTENT_ATTRIBUTE:
            
            if root.has_attr( self._attribute_to_fetch ):
                
                unknown_attr_result = root[ self._attribute_to_fetch ]
                
                # 'class' attr returns a list because it has multiple values under html spec, wew
                if isinstance( unknown_attr_result, list ):
                    
                    if len( unknown_attr_result ) == 0:
                        
                        raise HydrusExceptions.ParseException( 'Attribute ' + self._attribute_to_fetch + ' not found!' )
                        
                    else:
                        
                        result = ' '.join( unknown_attr_result )
                        
                    
                else:
                    
                    result = unknown_attr_result
                    
                
            else:
                
                raise HydrusExceptions.ParseException( 'Attribute ' + self._attribute_to_fetch + ' not found!' )
                
            
        elif self._content_to_fetch == HTML_CONTENT_STRING:
            
            result = root.string
            
        elif self._content_to_fetch == HTML_CONTENT_HTML:
            
            result = unicode( root )
            
        
        if result is None or result == '':
            
            raise HydrusExceptions.ParseException( 'Empty/No results found!' )
            
        else:
            
            self._string_match.Test( result )
            
            return self._string_converter.Convert( result )
            
        
    
    def _ParseTags( self, root, name, attrs, index ):
        
        results = root.find_all( name = name, attrs = attrs )
        
        if index is not None:
            
            if len( results ) < index + 1:
                
                results = []
                
            else:
                
                results = [ results[ index ] ]
                
            
        
        return results
        
    
    def _UpdateSerialisableInfo( self, version, old_serialisable_info ):
        
        if version == 1:
            
            ( tag_rules, attribute_to_fetch ) = old_serialisable_info
            
            culling_and_adding = ( 0, 0, '', '' )
            
            new_serialisable_info = ( tag_rules, attribute_to_fetch, culling_and_adding )
            
            return ( 2, new_serialisable_info )
            
        
        if version == 2:
            
            ( tag_rules, attribute_to_fetch, culling_and_adding ) = old_serialisable_info
            
            ( cull_front, cull_back, prepend, append ) = culling_and_adding
            
            transformations = []
            
            if cull_front > 0:
                
                transformations.append( ( STRING_TRANSFORMATION_CLIP_TEXT_FROM_BEGINNING, cull_front ) )
                
            elif cull_front < 0:
                
                transformations.append( ( STRING_TRANSFORMATION_REMOVE_TEXT_FROM_END, cull_front ) )
                
            
            if cull_back > 0:
                
                transformations.append( ( STRING_TRANSFORMATION_CLIP_TEXT_FROM_END, cull_back ) )
                
            elif cull_back < 0:
                
                transformations.append( ( STRING_TRANSFORMATION_REMOVE_TEXT_FROM_BEGINNING, cull_back ) )
                
            
            if prepend != '':
                
                transformations.append( ( STRING_TRANSFORMATION_PREPEND_TEXT, prepend ) )
                
            
            if append != '':
                
                transformations.append( ( STRING_TRANSFORMATION_APPEND_TEXT, append ) )
                
            
            string_converter = StringConverter( transformations, 'parsed information' )
            
            serialisable_string_converter = string_converter.GetSerialisableTuple()
            
            new_serialisable_info = ( tag_rules, attribute_to_fetch, serialisable_string_converter )
            
            return ( 3, new_serialisable_info )
            
        
        if version == 3:
            
            ( tag_rules, attribute_to_fetch, serialisable_string_converter ) = old_serialisable_info
            
            string_match = StringMatch()
            
            serialisable_string_match = string_match.GetSerialisableTuple()
            
            new_serialisable_info = ( tag_rules, attribute_to_fetch, serialisable_string_match, serialisable_string_converter )
            
            return ( 4, new_serialisable_info )
            
        
        if version == 4:
            
            ( tag_rules, attribute_to_fetch, serialisable_string_match, serialisable_string_converter ) = old_serialisable_info
            
            if attribute_to_fetch is None:
                
                content_to_fetch = HTML_CONTENT_STRING
                attribute_to_fetch = ''
                
            else:
                
                content_to_fetch = HTML_CONTENT_ATTRIBUTE
                
            
            new_serialisable_info = ( tag_rules, content_to_fetch, attribute_to_fetch, serialisable_string_match, serialisable_string_converter )
            
            return ( 5, new_serialisable_info )
            
        
    
    def Parse( self, html ):
        
        root = bs4.BeautifulSoup( html, 'lxml' )
        
        roots = ( root, )
        
        for ( name, attrs, index ) in self._tag_rules:
            
            next_roots = []
            
            for root in roots:
                
                next_roots.extend( self._ParseTags( root, name, attrs, index ) )
                
            
            roots = next_roots
            
        
        contents = []
        
        for root in roots:
            
            try:
                
                content = self._ParseContent( root )
                
                contents.append( content )
                
            except HydrusExceptions.ParseException:
                
                continue
                
            
        
        return contents
        
    
    def ToPrettyMultilineString( self ):
        
        pretty_strings = []
        
        for ( name, attrs, index ) in self._tag_rules:
            
            s = ''
            
            if index is None:
                
                s += 'get every'
                
            else:
                
                num = index + 1
                
                s += 'get the ' + HydrusData.ConvertIntToPrettyOrdinalString( num )
                
            
            s += ' <' + name + '> tag'
            
            if len( attrs ) > 0:
                
                s += ' with attributes ' + ', '.join( key + '=' + value for ( key, value ) in attrs.items() )
                
            
            pretty_strings.append( s )
            
        
        if self._content_to_fetch == HTML_CONTENT_ATTRIBUTE:
            
            pretty_strings.append( 'get the ' + self._attribute_to_fetch + ' attribute of those tags' )
            
        elif self._content_to_fetch == HTML_CONTENT_STRING:
            
            pretty_strings.append( 'get the text content of those tags' )
            
        elif self._content_to_fetch == HTML_CONTENT_HTML:
            
            pretty_strings.append( 'get the html of those tags' )
            
        
        pretty_strings.extend( self._string_converter.GetTransformationStrings() )
        
        separator = os.linesep + 'and then '
        
        pretty_multiline_string = separator.join( pretty_strings )
        
        return pretty_multiline_string
        
    
    def ToTuple( self ):
        
        return ( self._tag_rules, self._content_to_fetch, self._attribute_to_fetch, self._string_match, self._string_converter )
        
    
HydrusSerialisable.SERIALISABLE_TYPES_TO_OBJECT_TYPES[ HydrusSerialisable.SERIALISABLE_TYPE_PARSE_FORMULA_HTML ] = ParseFormulaHTML

class ContentParser( HydrusSerialisable.SerialisableBase ):
    
    SERIALISABLE_TYPE = HydrusSerialisable.SERIALISABLE_TYPE_CONTENT_PARSER
    SERIALISABLE_NAME = 'Content Parser'
    SERIALISABLE_VERSION = 1
    
    def __init__( self, name = None, content_type = None, formula = None, additional_info = None ):
        
        if name is None:
            
            name = ''
            
        
        if content_type is None:
            
            content_type = HC.CONTENT_TYPE_MAPPINGS
            
        
        if formula is None:
            
            formula = ParseFormulaHTML()
            
        
        if additional_info is None:
            
            if content_type == HC.CONTENT_TYPE_MAPPINGS:
                
                additional_info = ''
                
            
        
        self._name = name
        self._content_type = content_type
        self._formula = formula
        self._additional_info = additional_info
        
    
    def _GetSerialisableInfo( self ):
        
        serialisable_formula = self._formula.GetSerialisableTuple()
        
        return ( self._name, self._content_type, serialisable_formula, self._additional_info )
        
    
    def _InitialiseFromSerialisableInfo( self, serialisable_info ):
        
        ( self._name, self._content_type, serialisable_formula, self._additional_info ) = serialisable_info
        
        if isinstance( self._additional_info, list ):
            
            self._additional_info = tuple( self._additional_info )
            
        
        self._formula = HydrusSerialisable.CreateFromSerialisableTuple( serialisable_formula )
        
    
    def GetName( self ):
        
        return self._name
        
    
    def GetParsableContent( self ):
        
        return { ( self._name, self._content_type, self._additional_info ) }
        
    
    def Parse( self, data ):
        
        parsed_texts = self._formula.Parse( data )
        
        if self._content_type == HC.CONTENT_TYPE_VETO:
            
            ( veto_if_matches_found, match_if_text_present, search_text ) = self._additional_info
            
            if match_if_text_present:
                
                match_found = True in [ search_text in parsed_text for parsed_text in parsed_texts ]
                
            else:
                
                match_found = True not in [ search_text in parsed_text for parsed_text in parsed_texts ]
                
            
            do_veto = ( veto_if_matches_found and match_found ) or ( not veto_if_matches_found and not match_found )
            
            if do_veto:
                
                raise HydrusExceptions.VetoException( self._name )
                
            else:
                
                return []
                
            
        else:
            
            content_description = ( self._name, self._content_type, self._additional_info )
            
            return [ ( content_description, parsed_text ) for parsed_text in parsed_texts ]
            
        
    
    def SetName( self, name ):
        
        self._name = name
        
    
    def ToPrettyStrings( self ):
        
        return ( self._name, 'content', ConvertParsableContentToPrettyString( self.GetParsableContent(), include_veto = True ) )
        
    
    def ToTuple( self ):
        
        return ( self._name, self._content_type, self._formula, self._additional_info )
        
    
HydrusSerialisable.SERIALISABLE_TYPES_TO_OBJECT_TYPES[ HydrusSerialisable.SERIALISABLE_TYPE_CONTENT_PARSER ] = ContentParser

class PageParser( HydrusSerialisable.SerialisableBaseNamed ):
    
    SERIALISABLE_TYPE = HydrusSerialisable.SERIALISABLE_TYPE_PAGE_PARSER
    SERIALISABLE_NAME = 'Page Parser'
    SERIALISABLE_VERSION = 1
    
    def __init__( self, name, parser_key = None, string_converter = None, can_produce_separated_content = False, separation_formula = None, separated_content_parsers = None, content_parsers = None, example_urls = None ):
        
        if parser_key is None:
            
            parser_key = HydrusData.GenerateKey()
            
        
        if string_converter is None:
            
            string_converter = StringConverter()
            
        
        if separation_formula is None:
            
            separation_formula = ParseFormulaHTML( tag_rules = [ ( 'div', { 'class' : 'thumb' }, None ) ], content_to_fetch = HTML_CONTENT_HTML )
            
        
        if separated_content_parsers is None:
            
            separated_content_parsers = []
            
        
        if content_parsers is None:
            
            content_parsers = []
            
        
        if example_urls is None:
            
            example_urls = []
            
        
        HydrusSerialisable.SerialisableBaseNamed.__init__( self, name )
        
        self._parser_key = parser_key
        self._string_converter = string_converter
        self._can_produce_separated_content = can_produce_separated_content
        self._separation_formula = separation_formula
        self._separated_content_parsers = separated_content_parsers
        self._content_parsers = content_parsers
        self._example_urls = example_urls
        
    
    def GetContentParsers( self ):
        
        return ( self._can_produce_separated_content, self._separation_formula, self._separated_content_parsers, self._content_parsers )
        
    
    def GetExampleURLs( self ):
        
        return self._example_urls
        
    
    def GetParserKey( self ):
        
        return self._parser_key
        
    
    def GetStringConverter( self ):
        
        return self._string_converter
        
    
    def Parse( self, page_data ):
        
        try:
            
            converted_page_data = self._string_converter.Convert( page_data )
            
        except HydrusExceptions.StringConvertException as e:
            
            raise HydrusExceptions.ParseException( unicode( e ) )
            
        
        separated_content_results = []
        
        if self._can_produce_separated_content:
            
            separated_data = self._separation_formula.Parse( converted_page_data )
            
            for sub_page_data in separated_data:
                
                sub_content_results = []
                
                for content_parser in self._separated_content_parsers:
                    
                    sub_content_results.extend( content_parser.Parse( sub_page_data ) )
                    
                
                separated_content_results.append( sub_content_results )
                
            
        
        content_results = []
        
        for content_parser in self._content_parsers:
            
            content_results.extend( content_parser.Parse( converted_page_data ) )
            
        
        return ( separated_content_results, content_results )
        
    
    def RegenerateParserKey( self ):
        
        self._parser_key = HydrusData.GenerateKey()
        
    
HydrusSerialisable.SERIALISABLE_TYPES_TO_OBJECT_TYPES[ HydrusSerialisable.SERIALISABLE_TYPE_PAGE_PARSER ] = PageParser

class ParseNodeContentLink( HydrusSerialisable.SerialisableBase ):
    
    SERIALISABLE_TYPE = HydrusSerialisable.SERIALISABLE_TYPE_PARSE_NODE_CONTENT_LINK
    SERIALISABLE_NAME = 'Content Parsing Link'
    SERIALISABLE_VERSION = 1
    
    def __init__( self, name = None, formula = None, children = None ):
        
        if name is None:
            
            name = ''
            
        
        if formula is None:
            
            formula = ParseFormulaHTML()
            
        
        if children is None:
            
            children = []
            
        
        self._name = name
        self._formula = formula
        self._children = children
        
    
    def _GetSerialisableInfo( self ):
        
        serialisable_formula = self._formula.GetSerialisableTuple()
        serialisable_children = [ child.GetSerialisableTuple() for child in self._children ]
        
        return ( self._name, serialisable_formula, serialisable_children )
        
    
    def _InitialiseFromSerialisableInfo( self, serialisable_info ):
        
        ( self._name, serialisable_formula, serialisable_children ) = serialisable_info
        
        self._formula = HydrusSerialisable.CreateFromSerialisableTuple( serialisable_formula )
        self._children = [ HydrusSerialisable.CreateFromSerialisableTuple( serialisable_child ) for serialisable_child in serialisable_children ]
        
    
    def GetParsableContent( self ):
        
        children_parsable_content = set()
        
        for child in self._children:
            
            children_parsable_content.update( child.GetParsableContent() )
            
        
        return children_parsable_content
        
    
    def Parse( self, job_key, data, referral_url ):
        
        search_urls = self.ParseURLs( job_key, data, referral_url )
        
        content = []
        
        for search_url in search_urls:
            
            job_key.SetVariable( 'script_status', 'fetching ' + search_url )
            
            network_job = ClientNetworking.NetworkJob( 'GET', search_url, referral_url = referral_url )
            
            network_job.OverrideBandwidth()
            
            HG.client_controller.network_engine.AddJob( network_job )
            
            try:
                
                network_job.WaitUntilDone()
                
            except HydrusExceptions.CancelledException:
                
                break
                
            except HydrusExceptions.NetworkException as e:
                
                if isinstance( e, HydrusExceptions.NotFoundException ):
                    
                    job_key.SetVariable( 'script_status', '404 - nothing found' )
                    
                    time.sleep( 2 )
                    
                    continue
                    
                elif isinstance( e, HydrusExceptions.NetworkException ):
                    
                    job_key.SetVariable( 'script_status', 'Network error! Details written to log.' )
                    
                    HydrusData.Print( 'Problem fetching ' + search_url + ':' )
                    HydrusData.PrintException( e )
                    
                    time.sleep( 2 )
                    
                    continue
                    
                else:
                    
                    raise
                    
                
            
            linked_data = network_job.GetContent()
            
            children_content = GetChildrenContent( job_key, self._children, linked_data, search_url )
            
            content.extend( children_content )
            
            if job_key.IsCancelled():
                
                raise HydrusExceptions.CancelledException()
                
            
        
        return content
        
    
    def ParseURLs( self, job_key, data, referral_url ):
        
        basic_urls = self._formula.Parse( data )
        
        absolute_urls = [ urlparse.urljoin( referral_url, basic_url ) for basic_url in basic_urls ]
        
        for url in absolute_urls:
            
            job_key.AddURL( url )
            
        
        return absolute_urls
        
    
    def ToPrettyStrings( self ):
        
        return ( self._name, 'link', ConvertParsableContentToPrettyString( self.GetParsableContent() ) )
        
    
    def ToTuple( self ):
        
        return ( self._name, self._formula, self._children )
        
    
HydrusSerialisable.SERIALISABLE_TYPES_TO_OBJECT_TYPES[ HydrusSerialisable.SERIALISABLE_TYPE_PARSE_NODE_CONTENT_LINK ] = ParseNodeContentLink

FILE_IDENTIFIER_TYPE_FILE = 0
FILE_IDENTIFIER_TYPE_MD5 = 1
FILE_IDENTIFIER_TYPE_SHA1 = 2
FILE_IDENTIFIER_TYPE_SHA256 = 3
FILE_IDENTIFIER_TYPE_SHA512 = 4
FILE_IDENTIFIER_TYPE_USER_INPUT = 5

file_identifier_string_lookup = {}

file_identifier_string_lookup[ FILE_IDENTIFIER_TYPE_FILE ] = 'the actual file (POST only)'
file_identifier_string_lookup[ FILE_IDENTIFIER_TYPE_MD5 ] = 'md5 hash'
file_identifier_string_lookup[ FILE_IDENTIFIER_TYPE_SHA1 ] = 'sha1 hash'
file_identifier_string_lookup[ FILE_IDENTIFIER_TYPE_SHA256 ] = 'sha256 hash'
file_identifier_string_lookup[ FILE_IDENTIFIER_TYPE_SHA512 ] = 'sha512 hash'
file_identifier_string_lookup[ FILE_IDENTIFIER_TYPE_USER_INPUT ] = 'custom user input'

# eventually transition this to be a flat 'generate page/gallery urls'
# the rest of the parsing system can pick those up automatically
# this nullifies the need for contentlink stuff, at least in its current borked form
class ParseRootFileLookup( HydrusSerialisable.SerialisableBaseNamed ):
    
    SERIALISABLE_TYPE = HydrusSerialisable.SERIALISABLE_TYPE_PARSE_ROOT_FILE_LOOKUP
    SERIALISABLE_NAME = 'File Lookup Script'
    SERIALISABLE_VERSION = 2
    
    def __init__( self, name, url = None, query_type = None, file_identifier_type = None, file_identifier_string_converter = None, file_identifier_arg_name = None, static_args = None, children = None ):
        
        HydrusSerialisable.SerialisableBaseNamed.__init__( self, name )
        
        self._url = url
        self._query_type = query_type
        self._file_identifier_type = file_identifier_type
        self._file_identifier_string_converter = file_identifier_string_converter
        self._file_identifier_arg_name = file_identifier_arg_name
        self._static_args = static_args
        self._children = children
        
    
    def _GetSerialisableInfo( self ):
        
        serialisable_children = [ child.GetSerialisableTuple() for child in self._children ]
        serialisable_file_identifier_string_converter = self._file_identifier_string_converter.GetSerialisableTuple()
        
        return ( self._url, self._query_type, self._file_identifier_type, serialisable_file_identifier_string_converter, self._file_identifier_arg_name, self._static_args, serialisable_children )
        
    
    def _InitialiseFromSerialisableInfo( self, serialisable_info ):
        
        ( self._url, self._query_type, self._file_identifier_type, serialisable_file_identifier_string_converter, self._file_identifier_arg_name, self._static_args, serialisable_children ) = serialisable_info
        
        self._children = [ HydrusSerialisable.CreateFromSerialisableTuple( serialisable_child ) for serialisable_child in serialisable_children ]
        self._file_identifier_string_converter = HydrusSerialisable.CreateFromSerialisableTuple( serialisable_file_identifier_string_converter )
        
    
    def _UpdateSerialisableInfo( self, version, old_serialisable_info ):
        
        if version == 1:
            
            ( url, query_type, file_identifier_type, file_identifier_encoding, file_identifier_arg_name, static_args, serialisable_children ) = old_serialisable_info
            
            transformations = []
            
            if file_identifier_encoding == HC.ENCODING_RAW:
                
                pass
                
            elif file_identifier_encoding == HC.ENCODING_HEX:
                
                transformations.append( ( STRING_TRANSFORMATION_ENCODE, 'hex' ) )
                
            elif file_identifier_encoding == HC.ENCODING_BASE64:
                
                transformations.append( ( STRING_TRANSFORMATION_ENCODE, 'base64' ) )
                
            
            file_identifier_string_converter = StringConverter( transformations, 'some hash bytes' )
            
            serialisable_file_identifier_string_converter = file_identifier_string_converter.GetSerialisableTuple()
            
            new_serialisable_info = ( url, query_type, file_identifier_type, serialisable_file_identifier_string_converter, file_identifier_arg_name, static_args, serialisable_children )
            
            return ( 2, new_serialisable_info )
            
        
    def ConvertMediaToFileIdentifier( self, media ):
        
        if self._file_identifier_type == FILE_IDENTIFIER_TYPE_USER_INPUT:
            
            raise Exception( 'Cannot convert media to file identifier--this script takes user input!' )
            
        elif self._file_identifier_type == FILE_IDENTIFIER_TYPE_SHA256:
            
            return media.GetHash()
            
        elif self._file_identifier_type in ( FILE_IDENTIFIER_TYPE_MD5, FILE_IDENTIFIER_TYPE_SHA1, FILE_IDENTIFIER_TYPE_SHA512 ):
            
            sha256_hash = media.GetHash()
            
            if self._file_identifier_type == FILE_IDENTIFIER_TYPE_MD5:
                
                hash_type = 'md5'
                
            elif self._file_identifier_type == FILE_IDENTIFIER_TYPE_SHA1:
                
                hash_type = 'sha1'
                
            elif self._file_identifier_type == FILE_IDENTIFIER_TYPE_SHA512:
                
                hash_type = 'sha512'
                
            
            try:
                
                ( other_hash, ) = HG.client_controller.Read( 'file_hashes', ( sha256_hash, ), 'sha256', hash_type )
                
                return other_hash
                
            except:
                
                raise Exception( 'I do not know that file\'s ' + hash_type + ' hash, so I cannot look it up!' )
                
            
        elif self._file_identifier_type == FILE_IDENTIFIER_TYPE_FILE:
            
            hash = media.GetHash()
            mime = media.GetMime()
            
            client_files_manager = HG.client_controller.client_files_manager
            
            try:
                
                path = client_files_manager.GetFilePath( hash, mime )
                
                return path
                
            except HydrusExceptions.FileMissingException as e:
                
                raise Exception( 'That file is not in the database\'s local files, so I cannot look it up!' )
                
            
        
    
    def FetchData( self, job_key, file_identifier ):
        
        # add gauge report hook and in-stream cancel support to the get/post calls
        
        request_args = dict( self._static_args )
        
        if self._file_identifier_type != FILE_IDENTIFIER_TYPE_FILE:
            
            request_args[ self._file_identifier_arg_name ] = self._file_identifier_string_converter.Convert( file_identifier )
            
        
        if self._query_type == HC.GET:
            
            if self._file_identifier_type == FILE_IDENTIFIER_TYPE_FILE:
                
                raise Exception( 'Cannot have a file as an argument on a GET query!' )
                
            
            full_request_url = ClientNetworking.CombineGETURLWithParameters( self._url, request_args )
            
            job_key.SetVariable( 'script_status', 'fetching ' + full_request_url )
            
            job_key.AddURL( full_request_url )
            
            network_job = ClientNetworking.NetworkJob( 'GET', full_request_url )
            
        elif self._query_type == HC.POST:
            
            if self._file_identifier_type == FILE_IDENTIFIER_TYPE_FILE:
                
                job_key.SetVariable( 'script_status', 'uploading file' )
                
                path  = file_identifier
                
                files = { self._file_identifier_arg_name : open( path, 'rb' ) }
                
            else:
                
                job_key.SetVariable( 'script_status', 'uploading identifier' )
                
                files = None
                
            
            network_job = ClientNetworking.NetworkJob( 'POST', self._url, body = request_args )
            
            network_job.SetFiles( files )
            
        
        # send nj to nj control on this panel here
        
        network_job.OverrideBandwidth()
        
        HG.client_controller.network_engine.AddJob( network_job )
        
        try:
            
            network_job.WaitUntilDone()
            
        except HydrusExceptions.NotFoundException:
            
            job_key.SetVariable( 'script_status', '404 - nothing found' )
            
            raise
            
        except HydrusExceptions.NetworkException as e:
            
            job_key.SetVariable( 'script_status', 'Network error!' )
            
            HydrusData.ShowException( e )
            
            raise
            
        
        if job_key.IsCancelled():
            
            raise HydrusExceptions.CancelledException()
            
        
        data = network_job.GetContent()
        
        return data
        
    
    def GetParsableContent( self ):
        
        children_parsable_content = set()
        
        for child in self._children:
            
            children_parsable_content.update( child.GetParsableContent() )
            
        
        return children_parsable_content
        
    
    def DoQuery( self, job_key, file_identifier ):
        
        try:
            
            try:
                
                data = self.FetchData( job_key, file_identifier )
                
            except HydrusExceptions.NetworkException as e:
                
                return []
                
            
            content_results = self.Parse( job_key, data )
            
            return content_results
            
        except HydrusExceptions.CancelledException:
            
            job_key.SetVariable( 'script_status', 'Cancelled!' )
            
            return []
            
        finally:
            
            job_key.Finish()
            
        
    
    def UsesUserInput( self ):
        
        return self._file_identifier_type == FILE_IDENTIFIER_TYPE_USER_INPUT
        
    
    def Parse( self, job_key, data ):
        
        content_results = GetChildrenContent( job_key, self._children, data, self._url )
        
        if len( content_results ) == 0:
            
            job_key.SetVariable( 'script_status', 'Did not find anything.' )
            
        else:
            
            job_key.SetVariable( 'script_status', 'Found ' + HydrusData.ConvertIntToPrettyString( len( content_results ) ) + ' rows.' )
            
        
        return content_results
        
    
    def SetChildren( self, children ):
        
        self._children = children
        
    
    def ToPrettyStrings( self ):
        
        return ( self._name, HC.query_type_string_lookup[ self._query_type ], 'File Lookup', ConvertParsableContentToPrettyString( self.GetParsableContent() ) )
        
    
    def ToTuple( self ):
        
        return ( self._name, self._url, self._query_type, self._file_identifier_type, self._file_identifier_string_converter,  self._file_identifier_arg_name, self._static_args, self._children )
        
    
HydrusSerialisable.SERIALISABLE_TYPES_TO_OBJECT_TYPES[ HydrusSerialisable.SERIALISABLE_TYPE_PARSE_ROOT_FILE_LOOKUP ] = ParseRootFileLookup

STRING_TRANSFORMATION_REMOVE_TEXT_FROM_BEGINNING = 0
STRING_TRANSFORMATION_REMOVE_TEXT_FROM_END = 1
STRING_TRANSFORMATION_PREPEND_TEXT = 2
STRING_TRANSFORMATION_APPEND_TEXT = 3
STRING_TRANSFORMATION_ENCODE = 4
STRING_TRANSFORMATION_DECODE = 5
STRING_TRANSFORMATION_CLIP_TEXT_FROM_BEGINNING = 6
STRING_TRANSFORMATION_CLIP_TEXT_FROM_END = 7
STRING_TRANSFORMATION_REVERSE = 8
STRING_TRANSFORMATION_REGEX_SUB = 9

transformation_type_str_lookup = {}

transformation_type_str_lookup[ STRING_TRANSFORMATION_REMOVE_TEXT_FROM_BEGINNING ] = 'remove text from beginning of string'
transformation_type_str_lookup[ STRING_TRANSFORMATION_REMOVE_TEXT_FROM_END ] = 'remove text from end of string'
transformation_type_str_lookup[ STRING_TRANSFORMATION_PREPEND_TEXT ] = 'prepend text'
transformation_type_str_lookup[ STRING_TRANSFORMATION_APPEND_TEXT ] = 'append text'
transformation_type_str_lookup[ STRING_TRANSFORMATION_ENCODE ] = 'encode'
transformation_type_str_lookup[ STRING_TRANSFORMATION_DECODE ] = 'decode'
transformation_type_str_lookup[ STRING_TRANSFORMATION_CLIP_TEXT_FROM_BEGINNING ] = 'take the start of the string'
transformation_type_str_lookup[ STRING_TRANSFORMATION_CLIP_TEXT_FROM_END ] = 'take the end of the string'
transformation_type_str_lookup[ STRING_TRANSFORMATION_REVERSE ] = 'reverse text'
transformation_type_str_lookup[ STRING_TRANSFORMATION_REGEX_SUB ] = 'regex substitution'

class StringConverter( HydrusSerialisable.SerialisableBase ):
    
    SERIALISABLE_TYPE = HydrusSerialisable.SERIALISABLE_TYPE_STRING_CONVERTER
    SERIALISABLE_NAME = 'String Converter'
    SERIALISABLE_VERSION = 1
    
    def __init__( self, transformations = None, example_string = None ):
        
        if transformations is None:
            
            transformations = []
            
        
        if example_string is None:
            
            example_string = 'example string'
            
        
        HydrusSerialisable.SerialisableBase.__init__( self )
        
        self.transformations = transformations
        
        self.example_string = example_string
        
    
    def _GetSerialisableInfo( self ):
        
        return ( self.transformations, self.example_string )
        
    
    def _InitialiseFromSerialisableInfo( self, serialisable_info ):
        
        ( serialisable_transformations, self.example_string ) = serialisable_info
        
        self.transformations = []
        
        for ( transformation_type, data ) in serialisable_transformations:
            
            if transformation_type == STRING_TRANSFORMATION_REGEX_SUB:
                
                data = tuple( data ) # convert from list to tuple thing
                
            
            self.transformations.append( ( transformation_type, data ) )
            
        
    
    def Convert( self, s, max_steps_allowed = None ):
        
        for ( i, transformation ) in enumerate( self.transformations ):
            
            try:
                
                ( transformation_type, data ) = transformation
                
                if transformation_type == STRING_TRANSFORMATION_REMOVE_TEXT_FROM_BEGINNING:
                    
                    num_chars = data
                    
                    s = s[ num_chars : ]
                    
                elif transformation_type == STRING_TRANSFORMATION_REMOVE_TEXT_FROM_END:
                    
                    num_chars = data
                    
                    s = s[ : - num_chars ]
                    
                elif transformation_type == STRING_TRANSFORMATION_CLIP_TEXT_FROM_BEGINNING:
                    
                    num_chars = data
                    
                    s = s[ : num_chars ]
                    
                elif transformation_type == STRING_TRANSFORMATION_CLIP_TEXT_FROM_END:
                    
                    num_chars = data
                    
                    s = s[ - num_chars : ]
                    
                elif transformation_type == STRING_TRANSFORMATION_PREPEND_TEXT:
                    
                    text = data
                    
                    s = text + s
                    
                elif transformation_type == STRING_TRANSFORMATION_APPEND_TEXT:
                    
                    text = data
                    
                    s = s + text
                    
                elif transformation_type == STRING_TRANSFORMATION_ENCODE:
                    
                    encode_type = data
                    
                    s = s.encode( encode_type )
                    
                elif transformation_type == STRING_TRANSFORMATION_DECODE:
                    
                    encode_type = data
                    
                    s = s.decode( encode_type )
                    
                elif transformation_type == STRING_TRANSFORMATION_REVERSE:
                    
                    s = s[::-1]
                    
                elif transformation_type == STRING_TRANSFORMATION_REGEX_SUB:
                    
                    ( pattern, repl ) = data
                    
                    s = re.sub( pattern, repl, s, flags = re.UNICODE )
                    
                
            except:
                
                raise HydrusExceptions.StringConvertException( 'ERROR: Could not apply "' + self.TransformationToUnicode( transformation ) + '" to string "' + repr( s ) + '".' )
                
            
            if max_steps_allowed is not None and i + 1 >= max_steps_allowed:
                
                return s
                
            
        
        return s
        
    
    def GetTransformationStrings( self ):
        
        return [ self.TransformationToUnicode( transformation ) for transformation in self.transformations ]
        
    
    @staticmethod
    def TransformationToUnicode( transformation ):
        
        ( transformation_type, data ) = transformation
        
        if transformation_type == STRING_TRANSFORMATION_REMOVE_TEXT_FROM_BEGINNING:
            
            return 'remove the first ' + HydrusData.ConvertIntToPrettyString( data ) + ' characters'
            
        elif transformation_type == STRING_TRANSFORMATION_REMOVE_TEXT_FROM_END:
            
            return 'remove the last ' + HydrusData.ConvertIntToPrettyString( data ) + ' characters'
            
        elif transformation_type == STRING_TRANSFORMATION_CLIP_TEXT_FROM_BEGINNING:
            
            return 'take the first ' + HydrusData.ConvertIntToPrettyString( data ) + ' characters'
            
        elif transformation_type == STRING_TRANSFORMATION_CLIP_TEXT_FROM_END:
            
            return 'take the first ' + HydrusData.ConvertIntToPrettyString( data ) + ' characters'
            
        elif transformation_type == STRING_TRANSFORMATION_PREPEND_TEXT:
            
            return 'prepend with "' + data + '"'
            
        elif transformation_type == STRING_TRANSFORMATION_APPEND_TEXT:
            
            return 'append with "' + data + '"'
            
        elif transformation_type == STRING_TRANSFORMATION_ENCODE:
            
            return 'encode to ' + data
            
        elif transformation_type == STRING_TRANSFORMATION_DECODE:
            
            return 'decode from ' + data
            
        elif transformation_type == STRING_TRANSFORMATION_REVERSE:
            
            return transformation_type_str_lookup[ STRING_TRANSFORMATION_REVERSE ]
            
        elif transformation_type == STRING_TRANSFORMATION_REGEX_SUB:
            
            return 'regex substitution: ' + HydrusData.ToUnicode( data )
            
        
    
HydrusSerialisable.SERIALISABLE_TYPES_TO_OBJECT_TYPES[ HydrusSerialisable.SERIALISABLE_TYPE_STRING_CONVERTER ] = StringConverter

STRING_MATCH_FIXED = 0
STRING_MATCH_FLEXIBLE = 1
STRING_MATCH_REGEX = 2
STRING_MATCH_ANY = 3

ALPHA = 0
ALPHANUMERIC = 1
NUMERIC = 2

class StringMatch( HydrusSerialisable.SerialisableBase ):
    
    SERIALISABLE_TYPE = HydrusSerialisable.SERIALISABLE_TYPE_STRING_MATCH
    SERIALISABLE_NAME = 'String Match'
    SERIALISABLE_VERSION = 1
    
    def __init__( self, match_type = STRING_MATCH_ANY, match_value = '', min_chars = None, max_chars = None, example_string = 'example string' ):
        
        HydrusSerialisable.SerialisableBase.__init__( self )
        # make a gui control that accepts one of these. displays expected input on the right and colours red/green (and does isvalid) based on current input
        # think about replacing the veto stuff above with this.
        
        self._match_type = match_type
        self._match_value = match_value
        
        self._min_chars = min_chars
        self._max_chars = max_chars
        
        self._example_string = example_string
        
    
    def _GetSerialisableInfo( self ):
        
        return ( self._match_type, self._match_value, self._min_chars, self._max_chars, self._example_string )
        
    
    def _InitialiseFromSerialisableInfo( self, serialisable_info ):
        
        ( self._match_type, self._match_value, self._min_chars, self._max_chars, self._example_string ) = serialisable_info
        
    
    def SetMaxChars( self, max_chars ):
        
        self._max_chars = max_chars
        
    
    def SetMinChars( self, min_chars ):
        
        self._min_chars = min_chars
        
    
    def Test( self, text ):
        
        text_len = len( text )
        
        presentation_text = '"' + text + '"'
        
        if self._min_chars is not None and text_len < self._min_chars:
            
            raise HydrusExceptions.StringMatchException( presentation_text + ' had fewer than ' + HydrusData.ConvertIntToPrettyString( self._min_chars ) + ' characters' )
            
        
        if self._max_chars is not None and text_len > self._max_chars:
            
            raise HydrusExceptions.StringMatchException( presentation_text + ' had more than ' + HydrusData.ConvertIntToPrettyString( self._max_chars ) + ' characters' )
            
        
        if self._match_type == STRING_MATCH_FIXED:
            
            if text != self._match_value:
                
                raise HydrusExceptions.StringMatchException( presentation_text + ' did not exactly match "' + self._match_value + '"' )
                
            
        elif self._match_type in ( STRING_MATCH_FLEXIBLE, STRING_MATCH_REGEX ):
            
            if self._match_type == STRING_MATCH_FLEXIBLE:
                
                if self._match_value == ALPHA:
                    
                    r = '^[a-zA-Z]+$'
                    fail_reason = ' had non-alpha characters'
                    
                elif self._match_value == ALPHANUMERIC:
                    
                    r = '^[a-zA-Z\d]+$'
                    fail_reason = ' had non-alphanumeric characters'
                    
                elif self._match_value == NUMERIC:
                    
                    r = '^\d+$'
                    fail_reason = ' had non-numeric characters'
                    
                
            elif self._match_type == STRING_MATCH_REGEX:
                
                r = self._match_value
                
                fail_reason = ' did not match "' + r + '"'
                
            
            if re.search( r, text, flags = re.UNICODE ) is None:
                
                raise HydrusExceptions.StringMatchException( presentation_text + fail_reason )
                
            
        elif self._match_type == STRING_MATCH_ANY:
            
            pass
            
        
    
    def ToTuple( self ):
        
        return ( self._match_type, self._match_value, self._min_chars, self._max_chars, self._example_string )
        
    
    def ToUnicode( self ):
        
        result = ''
        
        if self._min_chars is None:
            
            if self._max_chars is None:
                
                result += 'any number of '
                
            else:
                
                result += 'at most ' + HydrusData.ToUnicode( self._max_chars ) + ' '
                
            
        else:
            
            if self._max_chars is None:
                
                result += 'at least ' + HydrusData.ToUnicode( self._min_chars ) + ' '
                
            else:
                
                result += 'between ' + HydrusData.ToUnicode( self._min_chars ) + ' and ' + HydrusData.ToUnicode( self._max_chars ) + ' '
                
            
        
        show_example = True
        
        if self._match_type == STRING_MATCH_ANY:
            
            result += 'characters'
            
            show_example = False
            
        elif self._match_type == STRING_MATCH_FIXED:
            
            result = self._match_value
            
            show_example = False
            
        elif self._match_type == STRING_MATCH_FLEXIBLE:
            
            if self._match_value == ALPHA:
                
                result += 'alphabetical characters'
                
            elif self._match_value == ALPHANUMERIC:
                
                result += 'alphanumeric characters'
                
            elif self._match_value == NUMERIC:
                
                result += 'numeric characters'
                
            
        elif self._match_type == STRING_MATCH_REGEX:
            
            result += 'characters, matching regex "' + self._match_value + '"'
            
        
        if show_example:
            
            result += ', such as "' + self._example_string + '"'
            
        
        return result
        
    
HydrusSerialisable.SERIALISABLE_TYPES_TO_OBJECT_TYPES[ HydrusSerialisable.SERIALISABLE_TYPE_STRING_MATCH ] = StringMatch
