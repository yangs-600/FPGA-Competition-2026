STATUS=ERROR
sby -f decoder_3_1.z.sby > /dev/null && STATUS=$(awk '{print $1}' decoder_3_1.z/status)
echo $STATUS > status
case $STATUS in
    PASS)
        echo "Proved equivalence of partition 'decoder_3_1.z' using strategy 'pdr'"
    ;;
    FAIL)
        echo "Could not prove equivalence of partition 'decoder_3_1.z' using strategy 'pdr': partitions not equivalent"
    ;;
    UNKNOWN)
        echo "Could not prove equivalence of partition 'decoder_3_1.z' using strategy 'pdr': equivalence unknown"
    ;;
    TIMEOUT)
        echo "Could not prove equivalence of partition 'decoder_3_1.z' using strategy 'pdr': timeout"
    ;;
    *)
        cat decoder_3_1.z/ERROR 2> /dev/null
        echo "Execution of strategy 'pdr' on partition 'decoder_3_1.z' encountered an error."
        echo "More details can be found in '/home/ubuntu/FPGA/clean-v11/shared-tree-tests-vfjtr0dr/decoder_3_1/proof/strategies/decoder_3_1.z/pdr/decoder_3_1.z/logfile.txt'."
        exit 1
    ;;
esac
exit 0

