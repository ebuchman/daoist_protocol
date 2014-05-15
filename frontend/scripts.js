
var daoAddr = "0x995db8d9f8f4dcc2b35da87a3768bd10eb8ee2da";

function strRepeat(x, n) {
    var s = '';
    for (;;) {
        if (n & 1) s += x;
        n >>= 1;
        if (n) x += x;
        else break;
    }
    return s;
}

function pad(x, n) {
    return (strRepeat("\x00", 32) + x).slice(-n);
}

function bigIntToHex(bi) {
    return Ethereum.util.encodeHex(Ethereum.util.intToBigEndian(bi));
}

function tiptag() {

    if (window.XMLHttpRequest)
        xmlhttp=new XMLHttpRequest();
    else
        xmlhttp=new ActiveXObject("Microsoft.XMLHTTP");

    var addr = daoAddr;
    var key = Ethereum.util.sha3('brain wallet');
    var msgsize = 2;
    var to_addr = document.getElementById("to").value;
    var value = parseInt(document.getElementById("value").value);
    var tohash =pad(msgsize.toString(16), 32) + pad(to_addr, 32) + pad(value, 32);

    var hash = Ethereum.util.sha3(tohash);
    var vrs = Ethereum.ecdsa.sign(Ethereum.convert.hexToBytes(hash), Ethereum.util.bigIntFromHex(key));

    data = JSON.stringify({
      'nonce': 1,
      'v': bigIntToHex(vrs[0]),
      'r': bigIntToHex(vrs[1]),
      's': bigIntToHex(vrs[2]),
      'addr': addr,
      'hash': hash,
      'msgsize': msgsize,
      'data': [to_addr, value]
      //'data': pad(document.getElementById("to").value, 32) + pad(document.getElementById("value").value, 32)
    });
    console.log(document.getElementById("value").value);
    console.log(data);
    xmlhttp.onreadystatechange = function() {
      document.getElementById("daocoin").innerText = xmlhttp.statusText;
      if (xmlhttp.readyState == 4 && xmlhttp.status == 200) {
        var response = JSON.parse(xmlhttp.responseText);
        if (vrs[0] == 0) {
          document.getElementById("daocoin").innerHTML = "Error signing request.";
        }
        else {
          document.getElementById("daocoin").innerHTML = "TAG! (" + xmlhttp.statusText + ")";
        }
      }
      else if (xmlhttp.readyState == 4)
        document.getElementById("daocoin").innerHTML = "Error! " + xmlhttp.status + ": " + xmlhttp.statusText;
    }
    var query_string = JSON.stringify(data);
    xmlhttp.open("POST", "http://127.0.0.1:30203/api/v0alpha/dc/", true);
    xmlhttp.setRequestHeader("Content-type", "application/json");
    xmlhttp.setRequestHeader("Content-length", query_string.length); 
    xmlhttp.send(query_string);
    return false;
}

updateBalances = function() {
  // getSomething();
  console.log(eth.balanceAt(eth.coinbase).dec());
  $("#eth").text(eth.balanceAt(eth.coinbase).dec());
  $("#daocoin").text(eth.storageAt(daoAddr, eth.coinbase).dec());
  $("#tot").text(eth.balanceAt(daoAddr).dec());
};

// $(document).ready(function() {
//   eth.watch(daoAddr, eth.coinbase, updateBalances);
//   updateBalances();
// });

/*
function tip_tag(){

  var daoAddr = "0x995db8d9f8f4dcc2b35da87a3768bd10eb8ee2da";
    var msgsize = "2";
    // var hash = CryptoJS.SHA3(msgsize.pad(32) + document.getElementById("to").value.pad(32) + document.getElementById("value").value.pad(32));
    var hash = Ethereum.util.sha3(msgsize.pad(32) + document.getElementById("to").value.pad(32) + document.getElementById("value").value.pad(32));
    // document.getElementById("daocoin").innerText = hash;
    var err;
    try {
      var vrs = Ethereum.ecdsa.sign(Ethereum.convert.hexToBytes(hash), Ethereum.util.bigIntFromHex(eth.key));
    }
    catch(e) {
      err = e;
      var vrs = [0, Ethereum.convert.hexToBytes(hash), Ethereum.util.bigIntFromHex(eth.key)];
    }
    // console.log(vrs);
    jQuery.ajax({
      url: "http://127.0.0.1:30203/api/v0alpha/dc/",
      // headers: {
      //   'Content-Type': 'application/json',
      // },
      //   'Accept': 'application/json'
      // },
      // crossDomain: true,
      type: "POST",
      data: JSON.stringify({
        "nonce": 1,
        "v": vrs[0],
        "r": vrs[1],
        "s": vrs[2],
        "adr": eth.secretToAddress(eth.key),
        "hash": hash,
        "fee": eth.gasPrice,
        "msgsize": msgsize,
        "data": document.getElementById("to").value.pad(32) + document.getElementById("value").value.pad(32)
      }),
      complete: function(e, status) {
        if (vrs[0] == 0)
          document.getElementById("daocoin").innerText = "Error! " + err;
        else
          document.getElementById("daocoin").innerText = "TAG! (" + status + ")";
      },
      error: function(e, status, error) {
        document.getElementById("daocoin").innerText = "Error! " + status + ": " + error;
      }
    });
    // eth.transact(
    //   eth.key,
    //   "0",
    //   gavAddr,
    //   eth.secretToAddress(document.getElementById("to").value).pad(32) + document.getElementById("value").value.pad(32),
    //   "10000",
    //   eth.gasPrice
    // );
  };
}
*/
